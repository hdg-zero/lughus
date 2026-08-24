"""Contract test: any StreamingLLM can be wrapped by BudgetedLLM.

The StreamingLLM protocol requires ``astream`` to be a coroutine that
returns an ``AsyncIterator``.  Both the real LLM and any wrapper (like
BudgetedLLM) must follow this contract so that the agent loop can use
``stream = await llm.astream(...)`` consistently.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.governance.budgeted_llm import BudgetedLLM
from lughus.testing import MockStreamingLLM


@pytest.mark.asyncio
async def test_budgeted_wraps_mock_streaming_llm():
    """MockStreamingLLM (coroutine-style) works when wrapped by BudgetedLLM."""
    inner = MockStreamingLLM(["Hello world."])
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(inner, ledger)

    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) > 0
    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1


@pytest.mark.asyncio
async def test_budgeted_wraps_mock_with_tool_calls():
    """MockStreamingLLM returning tool calls works through BudgetedLLM."""
    inner = MockStreamingLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "hi"}}],
        ]
    )
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(inner, ledger)

    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    assert len(chunks) > 0
    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1


@pytest.mark.asyncio
async def test_budgeted_abort_after_chunks_settles():
    """Closing a BudgetedLLM stream after consuming chunks settles the budget."""
    inner = MockStreamingLLM(["A long response with multiple tokens."])
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(inner, ledger)

    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])
    await stream.__anext__()
    await stream.aclose()

    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_budgeted_abort_before_chunks_releases():
    """Closing a BudgetedLLM stream before any chunk releases the reservation."""
    inner = MockStreamingLLM(["response"])
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(inner, ledger)

    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])
    await stream.aclose()

    snap = await ledger.snapshot()
    assert snap["model_calls"] == 0
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_budgeted_cancellation_after_chunks_settles():
    """CancelledError after consuming chunks settles the budget."""
    inner = MockStreamingLLM(["A response."])
    ledger = BudgetLedger(BudgetLimit())
    llm = BudgetedLLM(inner, ledger)

    stream = await llm.astream(messages=[{"role": "user", "content": "hi"}])
    await stream.__anext__()

    with contextlib.suppress(StopAsyncIteration, asyncio.CancelledError):
        await stream.athrow(asyncio.CancelledError)

    snap = await ledger.snapshot()
    assert snap["model_calls"] == 1
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0


@pytest.mark.asyncio
async def test_await_protocol_consistency():
    """Both plain and budgeted LLMs use the same await-then-iterate pattern."""
    inner = MockStreamingLLM(["test"])
    ledger = BudgetLedger(BudgetLimit())
    budgeted = BudgetedLLM(inner, ledger)

    inner2 = MockStreamingLLM(["test"])

    plain_stream = await inner2.astream(messages=[{"role": "user", "content": "hi"}])
    budgeted_stream = await budgeted.astream(messages=[{"role": "user", "content": "hi"}])

    assert hasattr(plain_stream, "__aiter__")
    assert hasattr(budgeted_stream, "__aiter__")
    assert hasattr(plain_stream, "__anext__")
    assert hasattr(budgeted_stream, "__anext__")
