"""Verify BudgetedLLM.astream settles on abort when chunks were emitted."""

import asyncio
import contextlib
from dataclasses import dataclass

import pytest

from lughus.budget import BudgetLedger, BudgetLimit
from lughus.budgeted_llm import BudgetedLLM


@dataclass
class _FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _Chunk:
    """Minimal chunk with optional usage attribute."""

    def __init__(self, text: str, usage: _FakeUsage | None = None) -> None:
        self.text = text
        self.usage = usage


class _FakeStreamingLLM:
    """Fake LLM that yields a configurable sequence of chunks."""

    model = "fake"
    timeout = 10.0

    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = chunks

    async def astream(self, *, messages: list[dict], tools: list[dict] | None = None):
        for chunk in self._chunks:
            yield chunk


# ── Tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_closed_after_first_chunk_settles():
    """When the consumer closes the stream after receiving at least one chunk,
    the budget must be settled (not released) because the provider billed."""
    chunks = [
        _Chunk("hello", _FakeUsage(10, 5)),
        _Chunk(" world", _FakeUsage(10, 10)),
        _Chunk(" end", _FakeUsage(10, 15)),
    ]
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(_FakeStreamingLLM(chunks), ledger)

    stream = llm.astream(messages=[{"role": "user", "content": "hi"}])
    first = await stream.__anext__()
    assert first.text == "hello"

    # Close the stream early (consumer done)
    await stream.aclose()

    # The budget should be settled, not released
    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1
    assert snap["tokens"] > 0  # actual usage recorded

    # No outstanding reservations
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_stream_closed_before_any_chunk_releases():
    """When the consumer closes the stream before any chunk is received,
    the budget reservation should be released (nothing billed)."""
    chunks = [
        _Chunk("hello", _FakeUsage(10, 5)),
    ]
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(_FakeStreamingLLM(chunks), ledger)

    stream = llm.astream(messages=[{"role": "user", "content": "hi"}])
    # Close immediately without consuming any chunk
    await stream.aclose()

    # The budget should be released (no cost recorded)
    snap = await ledger.snapshot()
    assert snap["model_calls"] == 0
    assert snap["tokens"] == 0

    # No outstanding reservations
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_full_stream_consumption_settles_normally():
    """Consuming the entire stream should settle the budget normally."""
    chunks = [
        _Chunk("hello", _FakeUsage(10, 5)),
        _Chunk(" world", _FakeUsage(10, 10)),
    ]
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(_FakeStreamingLLM(chunks), ledger)

    received = []
    async for chunk in llm.astream(messages=[{"role": "user", "content": "hi"}]):
        received.append(chunk.text)

    assert received == ["hello", " world"]
    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1
    assert snap["tokens"] == 20

    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_task_cancellation_treated_as_closure():
    """CancelledError thrown into the generator after chunks were emitted
    should settle (not release), same as GeneratorExit."""
    chunks = [
        _Chunk("hello", _FakeUsage(10, 5)),
        _Chunk(" world", _FakeUsage(10, 10)),
        _Chunk(" end", _FakeUsage(10, 15)),
    ]
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(_FakeStreamingLLM(chunks), ledger)

    stream = llm.astream(messages=[{"role": "user", "content": "hi"}])
    first = await stream.__anext__()
    assert first.text == "hello"

    # Throw CancelledError directly into the generator (same path as
    # task cancellation once the exception reaches the generator frame).
    with contextlib.suppress(StopAsyncIteration, asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError)

    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1
    assert snap["tokens"] > 0

    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_abort_loop_cannot_spend_without_cap():
    """A loop that systematically aborts streams after the first chunk must
    still accumulate cost in the ledger (the bug this ticket fixes)."""
    ledger = BudgetLedger(BudgetLimit(model_calls=100))
    chunks = [
        _Chunk("a", _FakeUsage(5, 5)),
        _Chunk("b", _FakeUsage(5, 10)),
        _Chunk("c", _FakeUsage(5, 15)),
    ]

    for _ in range(10):
        inner = _FakeStreamingLLM(chunks)
        llm = BudgetedLLM(inner, ledger)
        stream = llm.astream(messages=[{"role": "user", "content": "hi"}])
        await stream.__anext__()  # consume one chunk
        await stream.aclose()

    snap = await ledger.snapshot()
    # Each aborted stream should have settled 1 model_call
    assert snap["model_calls"] == 10
    # Each aborted stream should have settled tokens from first chunk usage
    assert snap["tokens"] > 0
