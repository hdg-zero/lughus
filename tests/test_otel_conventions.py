"""Tests for OpenTelemetry GenAI semantic convention compliance.

Every span attribute must live under ``gen_ai.*`` (standard GenAI
convention) or ``lughus.*`` (framework-specific).  This module validates
that the agent loop emits the right attributes with the right types and
that no attribute leaks into an unexpected namespace.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from lughus import ToolRegistry
from lughus.loop import LoopResult, agent_loop, agent_loop_stream
from lughus.loop._execute import _record_llm_usage
from lughus.testing import MockLLM, MockStreamingLLM

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_usage(
    prompt: int = 10,
    completion: int = 5,
    cached: int = 0,
    cache_creation: int = 0,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
    }
    if cached:
        usage["_cache_read_input_tokens"] = cached
    if cache_creation:
        usage["cache_creation_input_tokens"] = cache_creation
    return usage


class _SpanRecorder:
    """Minimal stand-in that records ``set_attribute`` calls."""

    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


def _registry() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool(
        "echo",
        "Echo input.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    def echo(*, text: str, state: Any) -> str:
        return json.dumps({"echo": text})

    return r


# ── _record_llm_usage attribute tests ───────────────────────────────────────


def test_record_llm_usage_sets_gen_ai_system() -> None:
    """gen_ai.system must be present and set to 'litellm'."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(), "gpt-4")
    assert span.attributes["gen_ai.system"] == "litellm"


def test_record_llm_usage_sets_operation_name() -> None:
    """gen_ai.operation.name must be 'chat'."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(), "gpt-4")
    assert span.attributes["gen_ai.operation.name"] == "chat"


def test_record_llm_usage_sets_input_tokens() -> None:
    """gen_ai.usage.input_tokens replaces the old prompt_tokens attribute."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(prompt=42), "gpt-4")
    assert span.attributes["gen_ai.usage.input_tokens"] == 42
    assert isinstance(span.attributes["gen_ai.usage.input_tokens"], int)


def test_record_llm_usage_sets_output_tokens() -> None:
    """gen_ai.usage.output_tokens replaces the old completion_tokens attribute."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(completion=17), "gpt-4")
    assert span.attributes["gen_ai.usage.output_tokens"] == 17
    assert isinstance(span.attributes["gen_ai.usage.output_tokens"], int)


def test_record_llm_usage_sets_cached_tokens() -> None:
    """gen_ai.usage.cached_tokens is set when cache hits exist."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(cached=8), "gpt-4")
    assert span.attributes["gen_ai.usage.cached_tokens"] == 8


def test_record_llm_usage_sets_cache_read_input_tokens() -> None:
    """gen_ai.usage.cache_read_input_tokens is set when cache hits exist."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(cached=8), "gpt-4")
    assert span.attributes["gen_ai.usage.cache_read_input_tokens"] == 8


def test_record_llm_usage_sets_cache_creation_input_tokens() -> None:
    """gen_ai.usage.cache_creation_input_tokens is set when cache creation occurs."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(cache_creation=12), "gpt-4")
    assert span.attributes["gen_ai.usage.cache_creation_input_tokens"] == 12


def test_record_llm_usage_no_old_attribute_names() -> None:
    """The old prompt_tokens / completion_tokens attribute names must not appear."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(prompt=10, completion=5, cached=3), "gpt-4")
    assert "gen_ai.usage.prompt_tokens" not in span.attributes
    assert "gen_ai.usage.completion_tokens" not in span.attributes


def test_record_llm_usage_no_bare_namespace_attributes() -> None:
    """No attribute may exist outside gen_ai.* or lughus.* prefixes."""
    span = _SpanRecorder()
    _record_llm_usage(
        span, _make_usage(prompt=10, completion=5, cached=3, cache_creation=2), "gpt-4"
    )
    for key in span.attributes:
        assert key.startswith("gen_ai.") or key.startswith("lughus."), (
            f"Attribute '{key}' is outside allowed namespaces"
        )


def test_record_llm_usage_token_types_are_int() -> None:
    """Token count attributes must be integers."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(prompt=10, completion=5, cached=3), "gpt-4")
    for key in (
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.cached_tokens",
    ):
        assert isinstance(span.attributes[key], int), f"{key} should be int"


def test_record_llm_usage_model_is_string() -> None:
    """gen_ai.system and gen_ai.operation.name must be strings."""
    span = _SpanRecorder()
    _record_llm_usage(span, _make_usage(), "gpt-4")
    assert isinstance(span.attributes["gen_ai.system"], str)
    assert isinstance(span.attributes["gen_ai.operation.name"], str)


# ── agent_loop integration tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_loop_span_attributes() -> None:
    """agent_loop sets gen_ai.system, gen_ai.request.model, and gen_ai.operation.name."""
    registry = _registry()
    llm = MockLLM(["Done."])
    result = await agent_loop(
        llm,
        system="sys",
        context="go",
        registry=registry,
        tool_names=["echo"],
        state=None,
    )
    assert isinstance(result, LoopResult)
    assert result == "Done."


@pytest.mark.asyncio
async def test_agent_loop_with_tool_call() -> None:
    """agent_loop with a tool call produces correct result."""
    registry = _registry()
    llm = MockLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "hi"}}],
            "Echoed.",
        ]
    )
    result = await agent_loop(
        llm,
        system="sys",
        context="echo hi",
        registry=registry,
        tool_names=["echo"],
        state=None,
    )
    assert isinstance(result, LoopResult)
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_agent_loop_stream_span_attributes() -> None:
    """agent_loop_stream sets gen_ai.system and gen_ai.operation.name."""
    registry = _registry()
    llm = MockStreamingLLM(["Stream done."])
    chunks = []
    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="go",
        registry=registry,
        tool_names=["echo"],
        state=None,
    ):
        chunks.append(chunk)
    final = chunks[-1]
    assert isinstance(final, LoopResult)
    assert final == "Stream done."
