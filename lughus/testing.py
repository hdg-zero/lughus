"""lughus.testing — test utilities for agent authors.

NOT imported by the main lughus package. Import explicitly:

    from lughus.testing import MockLLM, MockStreamingLLM
"""
from __future__ import annotations

import copy
import json
from typing import Any, AsyncIterator
from unittest.mock import MagicMock


def _make_text_response(text: str, model: str = "test/mock-model") -> MagicMock:
    """Build a fake non-streaming LLM response with text content."""
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.prompt_tokens_details = None
    usage._cache_read_input_tokens = 0

    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _make_tool_call_response(
    tool_calls: list[dict],
    model: str = "test/mock-model",
) -> MagicMock:
    """Build a fake LLM response that requests one or more tool calls."""
    usage = MagicMock()
    usage.prompt_tokens = 15
    usage.completion_tokens = 8
    usage.prompt_tokens_details = None
    usage._cache_read_input_tokens = 0

    tc_mocks = []
    for i, tc in enumerate(tool_calls):
        fn = MagicMock()
        fn.name = tc["name"]
        fn.arguments = json.dumps(tc.get("arguments", {}))

        tc_mock = MagicMock()
        tc_mock.id = tc.get("id", f"call_{i}")
        tc_mock.function = fn
        tc_mocks.append(tc_mock)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = tc_mocks

    choice = MagicMock()
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


class MockLLM:
    """Simulates an LLM without network calls.

    Pass a list of responses:
    - ``str`` → text response (ends the loop)
    - ``list[dict]`` → tool call response (continues the loop)

    Example::

        llm = MockLLM([
            [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
            "Hello World!",
        ])
    """

    model = "test/mock-model"
    timeout: float | None = None

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []  # record of (messages, tools) for assertions

    async def generate(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> MagicMock:
        self.calls.append({
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
        })
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return _make_text_response(resp)
        return _make_tool_call_response(resp)


# ── Streaming helpers ─────────────────────────────────────────────────────────


def _make_streaming_chunk(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    usage: MagicMock | None = None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Build a fake streaming chunk (delta-based)."""
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = []

    if tool_calls:
        tc_deltas = []
        for i, tc in enumerate(tool_calls):
            fn_delta = MagicMock()
            fn_delta.name = tc.get("name", "")
            fn_delta.arguments = json.dumps(tc.get("arguments", {}))

            tc_delta = MagicMock()
            tc_delta.index = i
            tc_delta.id = tc.get("id", f"call_{i}")
            tc_delta.function = fn_delta
            tc_deltas.append(tc_delta)
        delta.tool_calls = tc_deltas

    choice = MagicMock()
    choice.delta = delta
    choice.finish_reason = finish_reason

    chunk = MagicMock()
    chunk.choices = [choice]
    chunk.usage = usage
    return chunk


def _make_streaming_usage() -> MagicMock:
    """Build a fake usage object for the final streaming chunk."""
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.prompt_tokens_details = None
    usage._cache_read_input_tokens = 0
    return usage


def _make_streaming_text_response(text: str) -> AsyncIterator[MagicMock]:
    """Build a fake async streaming response for a text reply."""
    words = text.split() or [text]
    usage = _make_streaming_usage()

    async def _aiter():
        for i, word in enumerate(words):
            sep = "" if i == 0 else " "
            yield _make_streaming_chunk(content=sep + word)
        # Final chunk: empty choices + usage (OpenAI pattern)
        final = MagicMock()
        final.choices = []
        final.usage = usage
        yield final

    return _aiter()


def _make_streaming_tool_response(tool_calls: list[dict]) -> AsyncIterator[MagicMock]:
    """Build a fake async streaming response for a tool call."""
    async def _aiter():
        # Single chunk carrying all tool call deltas
        yield _make_streaming_chunk(tool_calls=tool_calls, finish_reason="tool_calls")
        # Final usage chunk
        final = MagicMock()
        final.choices = []
        final.usage = _make_streaming_usage()
        yield final

    return _aiter()


class MockStreamingLLM:
    """Simulates a streaming LLM without network calls.

    Pass a list of responses:
    - ``str`` → streaming text response (ends the loop)
    - ``list[dict]`` → streaming tool call response (continues the loop)

    Example::

        llm = MockStreamingLLM([
            [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
            "Hello World!",
        ])
    """

    model = "test/mock-model"
    timeout: float | None = None

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def astream(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[MagicMock]:
        self.calls.append({
            "messages": copy.deepcopy(messages),
            "tools": copy.deepcopy(tools),
        })
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return _make_streaming_text_response(resp)
        return _make_streaming_tool_response(resp)
