import asyncio

import pytest

from lughus.application import AgentRuntime
from lughus.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)
from lughus.budget import BudgetLedger, BudgetLimit
from lughus.context import ContextManager
from lughus.domain import RunEvent
from lughus.errors import ApprovalRequiredGroup
from lughus.event_stream import InMemoryEventSink
from lughus.idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    InMemoryIdempotencyStore,
)
from lughus.loop import ToolExecutionConfig, _execute_tools
from lughus.persistence import Checkpoint, InMemoryRunStore
from lughus.policy import LeastPrivilegePolicy, Principal
from lughus.runtime import ExecutionRuntime, RuntimeConfig
from lughus.tools import ToolRegistry, ToolRisk


@pytest.mark.asyncio
async def test_idempotency_claim_is_atomic():
    store = InMemoryIdempotencyStore()
    key = IdempotencyKey.from_args("run", "charge", {"amount": 1})
    gate = asyncio.Event()

    async def claim():
        await gate.wait()
        return await store.claim(ExecutionAttempt(key, AttemptStatus.PENDING))

    tasks = [asyncio.create_task(claim()) for _ in range(2)]
    gate.set()
    results = await asyncio.gather(*tasks)
    assert sum(result is None for result in results) == 1


@pytest.mark.asyncio
async def test_approved_proposal_is_reusable_by_digest():
    store = InMemoryApprovalStore()
    digest = proposal_digest("charge", {"amount": 1})
    request = ApprovalRequest("run", "charge", digest, "high")
    await store.create(request)
    await store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")
    assert (await store.find("run", digest)).status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approved_proposal_is_consumed_after_execution():
    store = InMemoryApprovalStore()
    digest = proposal_digest("charge", {"amount": 100})
    request = ApprovalRequest("run_1", "charge", digest, "high")
    await store.create(request)
    await store.decide(request.request_id, ApprovalStatus.APPROVED, "admin")

    registry = ToolRegistry()

    @registry.tool(
        "charge",
        "Charge account",
        {"type": "object", "properties": {"amount": {"type": "integer"}}},
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def charge(*, state: dict, amount: int) -> str:
        return f"charged_{amount}"

    runtime = ExecutionRuntime()
    cfg = ToolExecutionConfig(
        principal=Principal(subject="user_1", tenant_id="tenant_1"),
        approval_store=store,
        run_id="run_1",
        runtime=runtime,
    )
    try:
        res = await _execute_tools([("tc_1", "charge", '{"amount": 100}')], registry, {}, cfg)
        assert res[0][1] == "charged_100"

        consumed_request = await store.get(request.request_id)
        assert consumed_request is not None
        assert consumed_request.status == ApprovalStatus.CONSUMED

        # Subsequent execution without new approval must raise ApprovalRequiredGroup
        with pytest.raises(ApprovalRequiredGroup):
            await _execute_tools([("tc_2", "charge", '{"amount": 100}')], registry, {}, cfg)
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_resource_slots_serialize_same_key():
    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=2, max_sync_workers=1))
    active = 0
    peak = 0

    async def work():
        nonlocal active, peak
        async with runtime.resource_slot("account:A"):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1

    await asyncio.gather(work(), work())
    assert peak == 1
    await runtime.close()


@pytest.mark.asyncio
async def test_event_stream_global_cursor():
    sink = InMemoryEventSink()

    # Append events across two different runs
    await sink.append(RunEvent("run.created", "run_A", 0))
    await sink.append(RunEvent("run.created", "run_B", 0))
    await sink.append(RunEvent("step.done", "run_A", 1))
    await sink.append(RunEvent("step.done", "run_B", 1))

    # Global subscription (run_id=None) must receive all 4 events in order
    # without missing run B's event 0
    received = []
    async for event in sink.subscribe(after_sequence=-1, run_id=None):
        received.append((event.run_id, event.sequence))
        if len(received) == 4:
            break

    assert received == [
        ("run_A", 0),
        ("run_B", 0),
        ("run_A", 1),
        ("run_B", 1),
    ]


@pytest.mark.asyncio
async def test_governed_runtime_060_e2e_gate():
    """Gate 0.6.0: proposal -> approval -> claim -> execute -> receipt -> checkpoint."""
    execution = ExecutionRuntime()
    policy = LeastPrivilegePolicy()
    approvals = InMemoryApprovalStore()
    idempotency = InMemoryIdempotencyStore()
    durable_store = InMemoryRunStore()
    events = InMemoryEventSink()
    budget = BudgetLedger(BudgetLimit(model_calls=10, tool_calls=10))
    context = ContextManager(10_000)
    principal = Principal(subject="alice", tenant_id="acme")

    runtime = AgentRuntime(
        execution=execution,
        policy=policy,
        approvals=approvals,
        idempotency=idempotency,
        run_store=durable_store,
        event_store=durable_store,
        checkpoint_store=durable_store,
        events=events,
        budget=budget,
        context=context,
    )

    registry = ToolRegistry()
    executed_count = 0

    @registry.tool(
        "transfer_funds",
        "Transfer funds to target account",
        {
            "type": "object",
            "properties": {
                "to_account": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["to_account", "amount"],
        },
        requires_approval=True,
        idempotent=True,
        risk=ToolRisk.HIGH,
    )
    async def transfer_funds(*, state: dict, to_account: str, amount: int) -> str:
        nonlocal executed_count
        executed_count += 1
        return f"transferred_{amount}_to_{to_account}"

    run_id = "run_gate_060"
    args_json = '{"to_account": "bob", "amount": 500}'

    # --- Phase 1: Proposal (Requires Approval) ---
    cfg = runtime.tool_config(run_id=run_id, principal=principal)
    with pytest.raises(ApprovalRequiredGroup):
        await _execute_tools([("tc_1", "transfer_funds", args_json)], registry, {}, cfg)

    digest = proposal_digest("transfer_funds", {"to_account": "bob", "amount": 500})
    pending_request = await approvals.find(run_id, digest)
    assert pending_request is not None
    assert pending_request.status == ApprovalStatus.PENDING

    # Save Checkpoint 1 (before dispatch restart)
    ckpt_1 = Checkpoint(
        run_id=run_id,
        version=1,
        sequence=1,
        state={"phase": "proposal"},
        pending_action="transfer_funds",
        pending_arguments_hash=digest,
    )
    await durable_store.save(ckpt_1, expected_version=None)

    # --- Restart 1: Simulate restart before approval & dispatch ---
    # Re-fetch checkpoint to verify integrity
    reloaded_ckpt_1 = await durable_store.latest(run_id)
    assert reloaded_ckpt_1.pending_action == "transfer_funds"

    # --- Phase 2: Approval -> Claim -> Execute -> Receipt ---
    await approvals.decide(pending_request.request_id, ApprovalStatus.APPROVED, "admin_user")

    # Re-dispatch tool execution
    results = await _execute_tools([("tc_1", "transfer_funds", args_json)], registry, {}, cfg)
    assert results[0][1] == "transferred_500_to_bob"
    assert executed_count == 1

    # Verify receipt & consumed approval
    consumed_req = await approvals.get(pending_request.request_id)
    assert consumed_req.status == ApprovalStatus.CONSUMED

    idem_key = IdempotencyKey.from_args(
        run_id, "transfer_funds", {"to_account": "bob", "amount": 500}
    )
    receipt = await idempotency.get(idem_key)
    assert receipt is not None
    assert receipt.status == AttemptStatus.COMPLETED
    assert receipt.result == "transferred_500_to_bob"

    # Save Checkpoint 2 (after dispatch)
    ckpt_2 = Checkpoint(
        run_id=run_id,
        version=2,
        sequence=2,
        state={"phase": "completed"},
        pending_action=None,
    )
    await durable_store.save(ckpt_2, expected_version=1)

    # --- Restart 2: Simulate restart after dispatch ---
    reloaded_ckpt_2 = await durable_store.latest(run_id)
    assert reloaded_ckpt_2.pending_action is None

    # --- Phase 3: Final verification & Idempotency Cached Re-invocation ---
    results_retry = await _execute_tools(
        [("tc_1_retry", "transfer_funds", args_json)], registry, {}, cfg
    )
    assert results_retry[0][1] == "transferred_500_to_bob"
    # Ensure tool was NOT executed again (cached hit)
    assert executed_count == 1

    await execution.close()
