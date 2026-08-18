"""Tests for single retry layer.

Verifies:
- Total retries = configured amount, not multiplied across layers
- After the first chunk is emitted in streaming, errors propagate (no retry)
- retry_max_elapsed bounds total retry duration (injected clock, no real sleep)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import litellm
import pytest

from lughus.llm import LLM, retry_budget
from lughus.loop import LoopResult, agent_loop_stream
from lughus.testing import (
    FakeChunk,
    FakeDelta,
    FakeStreamChoice,
    FakeUsage,
    MockStreamingLLM,
)
from lughus.tools import ToolRegistry


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeStream:
    """Async iterator that yields pre-built chunks then optionally raises."""

    def __init__(self, chunks: list[Any], error: Exception | None = None) -> None:
        self._chunks = list(chunks)
        self._error = error
        self._index = 0

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> Any:
        if self._index < len(self._chunks):
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk
        if self._error is not None:
            err = self._error
            self._error = None
            raise err
        raise StopAsyncIteration


def _text_chunk(text: str) -> FakeChunk:
    """Build a streaming chunk carrying text content."""
    return FakeChunk(
        choices=(FakeStreamChoice(delta=FakeDelta(content=text)),),
    )


def _usage_chunk() -> FakeChunk:
    """Build a trailing usage-only chunk."""
    return FakeChunk(choices=(), usage=FakeUsage())


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_retries_not_multiplied(monkeypatch: pytest.MonkeyPatch) -> None:
    """With one retry layer, total attempts = max_retries + 1 (not squared).

    Previously, agent_loop_stream had its own retry on top of LLM._with_retry,
    causing (max_retries+1)^2 total calls. This verifies the multiplication is
    gone.
    """
    call_count = 0

    async def mock_acompletion(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise litellm.RateLimitError("429", "openai", "test/model")

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    llm = LLM("test/model", max_retries=2, retry_base_delay=0.0, retry_max_elapsed=None)

    with pytest.raises(litellm.RateLimitError):
        await llm.astream(messages=[{"role": "user", "content": "hi"}])

    # 1 initial try + 2 retries = 3 total, NOT 9
    assert call_count == 3


@pytest.mark.asyncio
async def test_no_retry_after_first_chunk_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once content has been yielded, a mid-stream error propagates without retry.

    A retry after emission would produce incoherent text because the consumer
    has already received partial content.
    """
    call_count = 0

    async def mock_acompletion(**kwargs: Any) -> _FakeStream:
        nonlocal call_count
        call_count += 1
        return _FakeStream(
            [_text_chunk("hello"), _text_chunk(" world")],
            error=litellm.APIConnectionError(
                "connection lost", llm_provider="openai", model="test/model"
            ),
        )

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=3, retry_base_delay=0.0, retry_max_elapsed=None)
    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])

    received: list[Any] = []
    with pytest.raises(litellm.APIConnectionError):
        async for chunk in stream:
            received.append(chunk)

    # Two chunks received before the error; no retry triggered
    assert len(received) == 2
    assert call_count == 1


@pytest.mark.asyncio
async def test_no_retry_after_emission_through_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration: agent_loop_stream does not add its own retry layer.

    The stream from llm.astream() is already retry-protected at the LLM level.
    Errors during iteration propagate straight through the loop.
    """
    registry = ToolRegistry()

    class FailAfterChunkLLM:
        model = "test/fail-mid-stream"
        timeout: float | None = None

        def __init__(self) -> None:
            self.call_count = 0

        async def astream(
            self, *, messages: list[dict], tools: list[dict] | None = None
        ) -> AsyncIterator[Any]:
            self.call_count += 1

            async def _gen() -> AsyncIterator[FakeChunk]:
                yield _text_chunk("partial")
                raise litellm.ServiceUnavailableError(
                    "503 gone", llm_provider="openai", model="test/fail-mid-stream"
                )

            return _gen()

    llm = FailAfterChunkLLM()
    emitted: list[str] = []

    with pytest.raises(litellm.ServiceUnavailableError):
        async for chunk in agent_loop_stream(
            llm,
            system="sys",
            context="ctx",
            registry=registry,
            tool_names=[],
            streaming_mode="live",
        ):
            emitted.append(chunk)

    assert emitted == ["partial"]
    assert llm.call_count == 1  # no retry at loop level


@pytest.mark.asyncio
async def test_retry_max_elapsed_bounds_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    """retry_max_elapsed prevents retrying beyond the time budget.

    Uses an injected clock (monkeypatched asyncio.sleep) -- no real sleeping.
    """
    sleeps: list[float] = []
    call_count = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def mock_acompletion(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        exc = litellm.RateLimitError("429", "openai", "test/model")
        exc.headers = {"Retry-After": "50.0"}
        raise exc

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=10, retry_base_delay=0.0, retry_max_elapsed=60.0)

    with pytest.raises(litellm.RateLimitError):
        await llm.astream(messages=[{"role": "user", "content": "hi"}])

    # Retry-After: 50s, budget 60s:
    #   attempt 0 fails -> delay 50, used 0+50=50 <= 60 -> sleep
    #   attempt 1 fails -> delay 50, used 50+50=100 > 60 -> raise
    assert call_count == 2
    assert sleeps == [50.0]


@pytest.mark.asyncio
async def test_retry_budget_shared_across_generate_and_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry budget context manager shares one budget across both
    generate() and astream() calls in the same context."""
    sleeps: list[float] = []
    call_count = 0

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def mock_acompletion(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        exc = litellm.RateLimitError("429", "openai", "test/model")
        exc.headers = {"Retry-After": "20.0"}
        raise exc

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    llm = LLM("test/model", max_retries=10, retry_base_delay=0.0)

    with retry_budget(30.0):
        # First call: sleeps 20s (within budget of 30s)
        with pytest.raises(litellm.RateLimitError):
            await llm.generate(messages=[{"role": "user", "content": "one"}])

        # Second call: would need 20s more, but only 10s left -> raises immediately
        with pytest.raises(litellm.RateLimitError):
            await llm.astream(messages=[{"role": "user", "content": "two"}])

    # First call: attempt 0 fails, sleep 20 (used=20), attempt 1 fails, sleep 20 (used=40>30) -> raise
    # Actually: attempt 0 fails, delay=20, used=0+20=20 <= 30 -> sleep, attempt 1 fails, delay=20, used=20+20=40 > 30 -> raise
    # Second call: attempt 0 fails, delay=20, used=20+20=40 > 30 -> raise immediately
    assert call_count == 3  # 2 from first call + 1 from second
    assert sleeps == [20.0]


@pytest.mark.asyncio
async def test_connection_level_retry_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection failures during astream are retried; the successful stream
    is returned to the caller."""
    call_count = 0

    async def mock_acompletion(**kwargs: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise litellm.APIConnectionError(
                "connection refused", llm_provider="openai", model="test/model"
            )
        return _FakeStream([_text_chunk("recovered"), _usage_chunk()])

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    llm = LLM("test/model", max_retries=3, retry_base_delay=0.0, retry_max_elapsed=None)
    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])

    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert call_count == 3
    assert len(chunks) == 2  # text chunk + usage chunk
