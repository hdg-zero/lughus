"""Verify integer-micros cost arithmetic eliminates floating-point drift."""

import pytest

from lughus.governance.budget import BudgetAmount, BudgetExceeded, BudgetLedger, BudgetLimit


@pytest.mark.asyncio
async def test_10000_additions_exact_total():
    """10 000 micro-cost additions must give an exact total.

    With float arithmetic ``0.0001 * 10_000 != 1.0`` due to rounding;
    integer micros are exact.
    """
    limit = BudgetLimit(estimated_cost_micros=1_000_000_000)
    ledger = BudgetLedger(limit)

    for _ in range(10_000):
        key = await ledger.reserve(BudgetAmount(estimated_cost_micros=100))
        await ledger.settle(key, BudgetAmount(estimated_cost_micros=100))

    snap = await ledger.snapshot()
    assert snap["estimated_cost_micros"] == 1_000_000
    # The equivalent float sum would be:
    #   sum(0.0001 for _ in range(10_000))  ->  0.9999999999999062  (not 1.0)
    # Integer micros are exact by construction.


@pytest.mark.asyncio
async def test_micros_limit_enforced():
    """Budget limit expressed in micros blocks excess reservation."""
    limit = BudgetLimit(estimated_cost_micros=500)
    ledger = BudgetLedger(limit)

    key = await ledger.reserve(BudgetAmount(estimated_cost_micros=400))
    with pytest.raises(BudgetExceeded, match="estimated_cost_micros"):
        await ledger.reserve(BudgetAmount(estimated_cost_micros=200))

    await ledger.settle(key, BudgetAmount(estimated_cost_micros=300))
    snap = await ledger.snapshot()
    assert snap["estimated_cost_micros"] == 300


@pytest.mark.asyncio
async def test_settle_idempotent():
    """Double settle on the same reservation is a no-op, not an error."""
    ledger = BudgetLedger(BudgetLimit())
    key = await ledger.reserve(BudgetAmount(tokens=10))
    await ledger.settle(key, BudgetAmount(tokens=8))

    # Second settle should silently no-op
    await ledger.settle(key, BudgetAmount(tokens=999))

    snap = await ledger.snapshot()
    assert snap["tokens"] == 8  # only the first settle counted


@pytest.mark.asyncio
async def test_outstanding_returns_current_reservations():
    """outstanding() exposes live reservations for observability."""
    ledger = BudgetLedger(BudgetLimit())

    key1 = await ledger.reserve(BudgetAmount(tokens=5))
    key2 = await ledger.reserve(BudgetAmount(tokens=3))
    outstanding = await ledger.outstanding()
    assert key1 in outstanding
    assert key2 in outstanding

    await ledger.settle(key1, BudgetAmount(tokens=4))
    outstanding = await ledger.outstanding()
    assert key1 not in outstanding
    assert key2 in outstanding

    await ledger.release(key2)
    outstanding = await ledger.outstanding()
    assert len(outstanding) == 0
