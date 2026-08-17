"""lughus.testing — test utilities for agent authors.

NOT imported by the main lughus package. Import explicitly::

    from lughus.testing import MockLLM, MockStreamingLLM

Why strict dataclasses instead of ``MagicMock`` (W1-13 / N-14)
-------------------------------------------------------------
This module used to build its fake responses with ``unittest.mock.MagicMock``.
A ``MagicMock`` answers *every* attribute access, which means:

* ``hasattr(chunk, "usage")`` is always ``True``;
* ``chunk.choices`` is always truthy;
* a misspelled attribute returns another mock instead of raising.

Tests therefore passed even when the loop read a field that does not exist, or
when an implementation violated its contract. That is the root cause of the
budget-x-streaming P0 (F-02) going unnoticed across several releases despite a
261-test suite: the doubles could not fail.

The ``Fake*`` dataclasses below reproduce *exactly* the response shape the loop
consumes -- no more, no less. An absent or misspelled attribute now raises
``AttributeError``, which is the behaviour a test double must have.

They are exported on purpose: together they are the executable specification of
the provider response shape Lughus expects, which is the information anyone
writing an alternative LLM client needs.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

# ── Response shape: non-streaming ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FakePromptTokensDetails:
    """``usage.prompt_tokens_details`` — OpenAI-style cached token reporting."""

    cached_tokens: int = 0


@dataclass(frozen=True, slots=True)
class FakeUsage:
    """Token accounting attached to a response or a final streaming chunk.

    ``cache_read_input_tokens`` is exposed under both its plain name and the
    underscore-prefixed alias ``_cache_read_input_tokens`` that Anthropic-style
    payloads use and that ``_extract_usage`` reads.
    """

    prompt_tokens: int = 10
    completion_tokens: int = 5
    prompt_tokens_details: FakePromptTokensDetails | None = None
    cache_read_input_tokens: int = 0

    @property
    def _cache_read_input_tokens(self) -> int:
        return self.cache_read_input_tokens


@dataclass(frozen=True, slots=True)
class FakeFunction:
    """``tool_call.function`` on a completed (non-streaming) response."""

    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class FakeToolCall:
    """A completed tool call request."""

    id: str
    function: FakeFunction
    type: str = "function"


@dataclass(frozen=True, slots=True)
class FakeMessage:
    """``choice.message`` on a completed response."""

    content: str | None = None
    tool_calls: tuple[FakeToolCall, ...] | None = None
    role: str = "assistant"


@dataclass(frozen=True, slots=True)
class FakeChoice:
    """``response.choices[i]`` for a completed response."""

    message: FakeMessage
    index: int = 0
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FakeResponse:
    """A completed (non-streaming) provider response."""

    choices: tuple[FakeChoice, ...] = ()
    usage: FakeUsage | None = None
    model: str = "test/mock-model"


# ── Response shape: streaming ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FakeFunctionDelta:
    """Incremental ``function`` payload inside a streaming tool-call delta."""

    name: str = ""
    arguments: str = ""


@dataclass(frozen=True, slots=True)
class FakeToolCallDelta:
    """Incremental tool call inside a streaming delta."""

    index: int
    id: str | None = None
    function: FakeFunctionDelta | None = None
    type: str = "function"


@dataclass(frozen=True, slots=True)
class FakeDelta:
    """``choice.delta`` on a streaming chunk.

    ``__bool__`` is explicit because the loop guards with ``if not delta``: an
    empty delta must be falsy, exactly as a provider's empty delta object is.
    """

    content: str | None = None
    tool_calls: tuple[FakeToolCallDelta, ...] = ()
    role: str | None = None

    def __bool__(self) -> bool:
        return bool(self.content) or bool(self.tool_calls) or self.role is not None


@dataclass(frozen=True, slots=True)
class FakeStreamChoice:
    """``chunk.choices[i]`` for a streaming chunk."""

    delta: FakeDelta
    index: int = 0
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FakeChunk:
    """One streaming chunk.

    A final usage-only chunk is ``FakeChunk(choices=(), usage=FakeUsage())``,
    which is the OpenAI ``stream_options={"include_usage": True}`` pattern.
    """

    choices: tuple[FakeStreamChoice, ...] = ()
    usage: FakeUsage | None = None
    model: str = "test/mock-model"


# ── Builders: non-streaming ───────────────────────────────────────────────────


def _make_text_response(text: str, model: str = "test/mock-model") -> FakeResponse:
    """Build a completed response carrying text content."""
    return FakeResponse(
        choices=(FakeChoice(message=FakeMessage(content=text), finish_reason="stop"),),
        usage=FakeUsage(prompt_tokens=10, completion_tokens=5),
        model=model,
    )


def _make_tool_call_response(
    tool_calls: Sequence[dict[str, Any]],
    model: str = "test/mock-model",
) -> FakeResponse:
    """Build a completed response requesting one or more tool calls."""
    calls = tuple(
        FakeToolCall(
            id=str(tc.get("id", f"call_{i}")),
            function=FakeFunction(
                name=str(tc["name"]),
                arguments=json.dumps(tc.get("arguments", {})),
            ),
        )
        for i, tc in enumerate(tool_calls)
    )
    return FakeResponse(
        choices=(
            FakeChoice(
                message=FakeMessage(content=None, tool_calls=calls),
                finish_reason="tool_calls",
            ),
        ),
        usage=FakeUsage(prompt_tokens=15, completion_tokens=8),
        model=model,
    )


# ── Builders: streaming ───────────────────────────────────────────────────────


def _make_streaming_usage() -> FakeUsage:
    """Build the usage object carried by a final streaming chunk."""
    return FakeUsage(prompt_tokens=10, completion_tokens=5)


def _make_streaming_chunk(
    content: str | None = None,
    tool_calls: Sequence[dict[str, Any]] | None = None,
    usage: FakeUsage | None = None,
    finish_reason: str | None = None,
) -> FakeChunk:
    """Build a delta-based streaming chunk."""
    deltas: tuple[FakeToolCallDelta, ...] = ()
    if tool_calls:
        deltas = tuple(
            FakeToolCallDelta(
                index=i,
                id=str(tc.get("id", f"call_{i}")),
                function=FakeFunctionDelta(
                    name=str(tc.get("name", "")),
                    arguments=json.dumps(tc.get("arguments", {})),
                ),
            )
            for i, tc in enumerate(tool_calls)
        )
    return FakeChunk(
        choices=(
            FakeStreamChoice(
                delta=FakeDelta(content=content, tool_calls=deltas),
                finish_reason=finish_reason,
            ),
        ),
        usage=usage,
    )


def _make_final_usage_chunk(usage: FakeUsage | None = None) -> FakeChunk:
    """Build the trailing usage-only chunk (no choices)."""
    return FakeChunk(choices=(), usage=usage or _make_streaming_usage())


def _make_streaming_text_response(text: str) -> AsyncIterator[FakeChunk]:
    """Build an async iterator streaming a text reply word by word."""
    words = text.split() or [text]

    async def _aiter() -> AsyncIterator[FakeChunk]:
        for i, word in enumerate(words):
            sep = "" if i == 0 else " "
            yield _make_streaming_chunk(content=sep + word)
        yield _make_final_usage_chunk()

    return _aiter()


def _make_streaming_tool_response(
    tool_calls: Sequence[dict[str, Any]],
) -> AsyncIterator[FakeChunk]:
    """Build an async iterator streaming a tool call request."""

    async def _aiter() -> AsyncIterator[FakeChunk]:
        yield _make_streaming_chunk(tool_calls=tool_calls, finish_reason="tool_calls")
        yield _make_final_usage_chunk()

    return _aiter()


# ── Doubles ───────────────────────────────────────────────────────────────────


class MockLLM:
    """Simulates a non-streaming LLM without network calls.

    Pass a list of responses:

    * ``str`` -> text response (ends the loop)
    * ``list[dict]`` -> tool call response (continues the loop)

    Example::

        llm = MockLLM(
            [
                [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
                "Hello World!",
            ]
        )
    """

    model = "test/mock-model"
    timeout: float | None = None

    def __init__(self, responses: Sequence[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> FakeResponse:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self._responses:
            raise AssertionError(
                f"MockLLM ran out of scripted responses after {len(self.calls)} call(s). "
                "The loop asked for more turns than the test provided."
            )
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return _make_text_response(resp)
        return _make_tool_call_response(resp)


class MockStreamingLLM:
    """Simulates a streaming LLM without network calls.

    Pass a list of responses:

    * ``str`` -> streaming text response (ends the loop)
    * ``list[dict]`` -> streaming tool call response (continues the loop)

    Example::

        llm = MockStreamingLLM(
            [
                [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
                "Hello World!",
            ]
        )
    """

    model = "test/mock-model"
    timeout: float | None = None

    def __init__(self, responses: Sequence[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def astream(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[FakeChunk]:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self._responses:
            raise AssertionError(
                f"MockStreamingLLM ran out of scripted responses after {len(self.calls)} call(s)."
            )
        resp = self._responses.pop(0)
        if isinstance(resp, str):
            return _make_streaming_text_response(resp)
        return _make_streaming_tool_response(resp)


__all__ = [
    "FakeChoice",
    "FakeChunk",
    "FakeDelta",
    "FakeFunction",
    "FakeFunctionDelta",
    "FakeMessage",
    "FakePromptTokensDetails",
    "FakeResponse",
    "FakeStreamChoice",
    "FakeToolCall",
    "FakeToolCallDelta",
    "FakeUsage",
    "MockLLM",
    "MockStreamingLLM",
]
