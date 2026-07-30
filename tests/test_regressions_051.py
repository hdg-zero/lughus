import pytest

from lughus.budget import BudgetAmount, BudgetLedger, BudgetLimit
from lughus.delegation import DelegationRequest, DelegationResult, Delegator
from lughus.domain import RunEvent
from lughus.event_stream import InMemoryEventSink
from lughus.idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    InMemoryIdempotencyStore,
)
from lughus.persistence import Checkpoint
from lughus.resume import ResumeAction, decide_resume


@pytest.mark.asyncio
async def test_event_sequences_are_scoped_per_run():
    sink = InMemoryEventSink()
    await sink.append(RunEvent("done", "run-a", 2))
    await sink.append(RunEvent("start", "run-b", 0))
    assert len(sink.snapshot()) == 2


@pytest.mark.asyncio
async def test_budget_records_observed_overage():
    ledger = BudgetLedger(BudgetLimit(tokens=10))
    a = await ledger.reserve(BudgetAmount(tokens=6))
    b = await ledger.reserve(BudgetAmount(tokens=4))
    await ledger.settle(a, BudgetAmount(tokens=7))
    await ledger.settle(b, BudgetAmount(tokens=4))
    assert (await ledger.snapshot())["tokens"] == 11
    assert await ledger.would_exceed() == ("tokens",)


@pytest.mark.asyncio
async def test_resume_uses_persisted_arguments_hash():
    store = InMemoryIdempotencyStore()
    key = IdempotencyKey.from_args("run", "charge", {"amount": 1})
    await store.save(ExecutionAttempt(key, AttemptStatus.COMPLETED, result="ok"))
    cp = Checkpoint(
        "run",
        1,
        1,
        {},
        pending_action="charge",
        outcome_unknown=True,
        pending_arguments_hash=key.arguments_hash,
    )
    assert (await decide_resume(cp, idempotency_store=store)).action == ResumeAction.COMPLETE


class _Remote:
    async def delegate(self, request):
        return DelegationResult("task", "completed")


@pytest.mark.asyncio
async def test_sequential_delegations_do_not_accumulate_depth():
    delegator = Delegator(_Remote(), BudgetLedger(BudgetLimit(delegation_depth=2)))
    for i in range(10):
        await delegator.delegate(DelegationRequest("run", f"agent-{i}", "skill", "objective"))
