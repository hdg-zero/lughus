import pytest

from lughus.core.context import ContextItem, ContextManager, TrustLevel
from lughus.core.domain import Run, RunEvent, RunStatus
from lughus.governance.budget import BudgetAmount, BudgetExceeded, BudgetLedger, BudgetLimit
from lughus.persistence import Checkpoint, ConcurrentUpdateError, InMemoryRunStore


@pytest.mark.asyncio
async def test_optimistic_run_updates_and_terminal_immutability():
    store = InMemoryRunStore()
    run = Run("objective")
    await store.create(run)
    updated = await store.update_status(run.run_id, 0, RunStatus.RUNNING)
    with pytest.raises(ConcurrentUpdateError, match="version"):
        await store.update_status(run.run_id, 0, RunStatus.COMPLETED)
    terminal = await store.update_status(run.run_id, updated.version, RunStatus.COMPLETED)
    with pytest.raises(ConcurrentUpdateError, match="Terminal"):
        await store.update_status(run.run_id, terminal.version, RunStatus.RUNNING)


@pytest.mark.asyncio
async def test_event_order_and_checkpoint_compare_and_swap():
    store = InMemoryRunStore()
    await store.append(RunEvent("started", "run", 0))
    with pytest.raises(ConcurrentUpdateError, match="monotonic"):
        await store.append(RunEvent("duplicate", "run", 0))
    checkpoint = Checkpoint("run", 0, 0, {"phase": "start"})
    await store.save(checkpoint, expected_version=None)
    with pytest.raises(ConcurrentUpdateError, match="version"):
        await store.save(Checkpoint("run", 1, 1, {}), expected_version=None)


@pytest.mark.asyncio
async def test_budget_reservation_is_atomic():
    ledger = BudgetLedger(
        BudgetLimit(
            model_calls=1,
            tool_calls=1,
            tokens=10,
            bytes=10,
            estimated_cost_micros=1,
            delegation_depth=1,
        )
    )
    reservation = await ledger.reserve(BudgetAmount(tokens=8))
    with pytest.raises(BudgetExceeded):
        await ledger.reserve(BudgetAmount(tokens=3))
    await ledger.settle(reservation, BudgetAmount(tokens=7))
    assert (await ledger.snapshot())["tokens"] == 7


def test_context_preserves_system_and_recent_items():
    manager = ContextManager(20)
    items = [
        ContextItem("system", "rules", "app", TrustLevel.SYSTEM),
        ContextItem("user", "old-message", "user", TrustLevel.USER),
        ContextItem("user", "recent", "user", TrustLevel.USER),
    ]
    window = manager.select(items)
    assert window.items[0].trust == TrustLevel.SYSTEM
    assert window.items[-1].content == "recent"
    assert window.omitted == 1
