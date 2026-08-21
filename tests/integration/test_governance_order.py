"""Integration tests verifying the eight-step governance order.

Governance pipeline:

  1. policy          deterministic, no side effects, always first
  2. receipt lookup  idempotent hit skips re-approval
  3. approval        check/create, WITHOUT consuming
  4. claim           write PENDING receipt, only after authorization
  5. slots           concurrency admission
  6. budget          reserved when dispatch is certain
  7. consumption     last mutation before dispatch
  8. dispatch
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from lughus.engine.tools import ToolRegistry, ToolRisk
from lughus.governance.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.governance.idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    InMemoryIdempotencyStore,
)
from lughus.governance.policy import DecisionKind, PolicyDecision, Principal, ToolProposal
from lughus.infra.runtime import ExecutionRuntime, RuntimeConfig
from lughus.loop._config import ToolExecutionConfig
from lughus.loop._execute import _execute_tools

# ── Helpers ──────────────────────────────────────────────

RUN_ID = "gov-test-run"
_PRINCIPAL = Principal("tester", "test-tenant", frozenset({"execute"}))


def owned_config(**kwargs: Any) -> ToolExecutionConfig:
    """Build a ToolExecutionConfig backed by a fresh ExecutionRuntime.

    The caller must close ``cfg.runtime`` after use.  Runtime-level
    capacities (``max_global_tools``, ``max_sync_workers``) are popped
    from *kwargs* so they reach ``RuntimeConfig`` only.
    """
    max_global = kwargs.pop("max_global_tools", 64)
    max_sync = kwargs.pop("max_sync_workers", 32)
    runtime = ExecutionRuntime(
        RuntimeConfig(max_global_tools=max_global, max_sync_workers=max_sync)
    )
    kwargs.setdefault("run_id", RUN_ID)
    return ToolExecutionConfig(runtime=runtime, **kwargs)


class _AllowPolicy:
    """Policy that allows every proposal."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        return PolicyDecision(DecisionKind.ALLOW, "allowed")


class _DenyPolicy:
    """Policy that denies every proposal."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        return PolicyDecision(DecisionKind.DENY, "blocked")


class _RequireApprovalPolicy:
    """Policy that requires approval for every proposal."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        return PolicyDecision(DecisionKind.REQUIRE_APPROVAL, "needs_approval")


def _pre_approve(
    store: InMemoryApprovalStore,
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> ApprovalRequest:
    """Synchronously create and approve a request, returning it."""
    arguments = args or {}
    digest = proposal_digest(tool_name, arguments)
    request = ApprovalRequest(RUN_ID, tool_name, digest, "high")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(store.create(request))
    loop.run_until_complete(store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer"))
    return request


# ── Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_not_consumed_when_claim_signals_in_progress():
    """Step 4 (claim) raises before step 7 (consumption).

    An idempotent tool whose execution is already PENDING must not consume
    the approval that was checked at step 3.
    """
    registry = ToolRegistry()

    @registry.tool(
        "idem_tool",
        "Idempotent tool.",
        {"type": "object", "properties": {}},
        idempotent=True,
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def idem_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    approval_store = InMemoryApprovalStore()
    idem_store = InMemoryIdempotencyStore()

    # Pre-approve
    digest = proposal_digest("idem_tool", {})
    request = ApprovalRequest(RUN_ID, "idem_tool", digest, "high")
    await approval_store.create(request)
    await approval_store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")

    # Plant a PENDING receipt so the claim sees an in-progress execution
    idem_key = IdempotencyKey.from_args(RUN_ID, "idem_tool", {})
    await idem_store.claim(ExecutionAttempt(key=idem_key, status=AttemptStatus.PENDING))

    cfg = owned_config(
        approval_store=approval_store,
        idempotency_store=idem_store,
        principal=_PRINCIPAL,
        policy=_AllowPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_1", "idem_tool", "{}")],
            registry,
            state=None,
            config=cfg,
        )
        data = json.loads(results[0][1])
        assert "error" in data, "Expected an error from the in-progress claim"
    finally:
        await cfg.runtime.close()

    # Approval must still be APPROVED -- not consumed
    final = await approval_store.get(request.request_id)
    assert final is not None
    assert final.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approval_not_consumed_when_budget_exceeds():
    """Step 6 (budget) raises before step 7 (consumption).

    When the budget is exhausted, the approval checked at step 3 must
    remain APPROVED so it can be retried once budget is replenished.
    """
    registry = ToolRegistry()

    @registry.tool(
        "budget_tool",
        "Tool with budget.",
        {"type": "object", "properties": {}},
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def budget_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    approval_store = InMemoryApprovalStore()
    digest = proposal_digest("budget_tool", {})
    request = ApprovalRequest(RUN_ID, "budget_tool", digest, "high")
    await approval_store.create(request)
    await approval_store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")

    # Budget with zero tool_calls: any reservation immediately fails
    budget = BudgetLedger(
        BudgetLimit(
            model_calls=100,
            tool_calls=0,
            tokens=1_000_000,
            bytes=100_000_000,
            estimated_cost_micros=100_000_000,
            delegation_depth=4,
        )
    )

    cfg = owned_config(
        approval_store=approval_store,
        budget=budget,
        principal=_PRINCIPAL,
        policy=_AllowPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_1", "budget_tool", "{}")],
            registry,
            state=None,
            config=cfg,
        )
        data = json.loads(results[0][1])
        assert "error" in data, "Expected a budget-exceeded error"
    finally:
        await cfg.runtime.close()

    # Approval must still be APPROVED
    final = await approval_store.get(request.request_id)
    assert final is not None
    assert final.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approval_not_consumed_when_slot_timeout():
    """Step 5 (slots) raises before step 7 (consumption).

    When no tool slot is available and the queue times out, the approval
    must remain APPROVED.
    """
    registry = ToolRegistry()

    started = asyncio.Event()
    release = asyncio.Event()

    @registry.tool(
        "blocker",
        "Blocks until released.",
        {"type": "object", "properties": {}},
    )
    async def blocker(*, state: Any) -> str:
        started.set()
        await release.wait()
        return json.dumps({"done": True})

    @registry.tool(
        "gated_tool",
        "Tool requiring approval.",
        {"type": "object", "properties": {}},
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def gated_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    approval_store = InMemoryApprovalStore()
    digest = proposal_digest("gated_tool", {})
    request = ApprovalRequest(RUN_ID, "gated_tool", digest, "high")
    await approval_store.create(request)
    await approval_store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")

    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=1, max_sync_workers=32))
    cfg = ToolExecutionConfig(
        runtime=runtime,
        run_id=RUN_ID,
        tool_queue_timeout=0.01,
        approval_store=approval_store,
        principal=_PRINCIPAL,
        policy=_AllowPolicy(),
    )

    try:
        # Occupy the single slot with the blocker
        blocker_task = asyncio.create_task(
            _execute_tools(
                [("call_block", "blocker", "{}")],
                registry,
                state=None,
                config=cfg,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # The gated tool should time out waiting for the slot
        results = await _execute_tools(
            [("call_gated", "gated_tool", "{}")],
            registry,
            state=None,
            config=cfg,
        )
        data = json.loads(results[0][1])
        assert "error" in data
        assert data["error"] == "ToolTimeoutError"
    finally:
        release.set()
        await asyncio.wait_for(blocker_task, timeout=2.0)
        await runtime.close()

    # Approval must still be APPROVED
    final = await approval_store.get(request.request_id)
    assert final is not None
    assert final.status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approval_consumed_on_successful_dispatch():
    """Step 7 (consumption) runs on the happy path before step 8 (dispatch).

    After successful execution, the approval transitions to CONSUMED.
    """
    registry = ToolRegistry()

    @registry.tool(
        "approved_tool",
        "Tool requiring approval.",
        {"type": "object", "properties": {}},
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def approved_tool(*, state: Any) -> str:
        return json.dumps({"result": "ok"})

    approval_store = InMemoryApprovalStore()
    digest = proposal_digest("approved_tool", {})
    request = ApprovalRequest(RUN_ID, "approved_tool", digest, "high")
    await approval_store.create(request)
    await approval_store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")

    cfg = owned_config(
        approval_store=approval_store,
        principal=_PRINCIPAL,
        policy=_AllowPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_1", "approved_tool", "{}")],
            registry,
            state=None,
            config=cfg,
        )
        data = json.loads(results[0][1])
        assert data["ok"] is True
        assert data["result"] == {"result": "ok"}
    finally:
        await cfg.runtime.close()

    final = await approval_store.get(request.request_id)
    assert final is not None
    assert final.status == ApprovalStatus.CONSUMED


@pytest.mark.asyncio
async def test_no_receipt_when_policy_denies():
    """Step 1 (policy) DENY prevents any receipt from being written.

    Because policy is the first gate, neither a PENDING claim nor a
    COMPLETED receipt should appear in the idempotency store.
    """
    registry = ToolRegistry()

    @registry.tool(
        "denied_tool",
        "Tool that will be denied.",
        {"type": "object", "properties": {}},
        idempotent=True,
    )
    async def denied_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    idem_store = InMemoryIdempotencyStore()

    cfg = owned_config(
        idempotency_store=idem_store,
        principal=_PRINCIPAL,
        policy=_DenyPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_1", "denied_tool", "{}")],
            registry,
            state=None,
            config=cfg,
        )
        data = json.loads(results[0][1])
        assert "error" in data
    finally:
        await cfg.runtime.close()

    key = IdempotencyKey.from_args(RUN_ID, "denied_tool", {})
    assert await idem_store.get(key) is None
    assert len(idem_store) == 0


@pytest.mark.asyncio
async def test_budget_not_reserved_during_slot_wait():
    """Step 6 (budget) happens inside step 5 (slot), not before.

    While a tool waits for a concurrency slot, the budget must not yet
    be reserved. Only the tool that already holds the slot has a
    reservation.
    """
    registry = ToolRegistry()

    started = asyncio.Event()
    release = asyncio.Event()

    @registry.tool(
        "blocker",
        "Blocks until released.",
        {"type": "object", "properties": {}},
    )
    async def blocker(*, state: Any) -> str:
        started.set()
        await release.wait()
        return json.dumps({"done": True})

    @registry.tool(
        "checked_tool",
        "Tool whose budget timing we observe.",
        {"type": "object", "properties": {}},
    )
    async def checked_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    budget = BudgetLedger(
        BudgetLimit(
            model_calls=100,
            tool_calls=10,
            tokens=1_000_000,
            bytes=100_000_000,
            estimated_cost_micros=100_000_000,
            delegation_depth=4,
        )
    )

    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=1, max_sync_workers=32))
    cfg = ToolExecutionConfig(
        runtime=runtime,
        run_id=RUN_ID,
        budget=budget,
    )

    try:
        # Fill the single slot with the blocker
        blocker_task = asyncio.create_task(
            _execute_tools(
                [("call_block", "blocker", "{}")],
                registry,
                state=None,
                config=cfg,
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2.0)

        # Launch the checked tool (it will wait for the slot)
        checked_task = asyncio.create_task(
            _execute_tools(
                [("call_check", "checked_tool", "{}")],
                registry,
                state=None,
                config=cfg,
            )
        )

        # Give the checked task time to reach the slot-wait point
        await asyncio.sleep(0.05)

        # Only the blocker (inside the slot) should have a reservation.
        # The checked_tool must NOT have reserved budget while waiting.
        assert len(budget._reserved) <= 1, (
            f"Expected at most 1 budget reservation (the blocker), got {len(budget._reserved)}"
        )

        release.set()
        await asyncio.wait_for(blocker_task, timeout=2.0)
        await asyncio.wait_for(checked_task, timeout=2.0)
    finally:
        await runtime.close()

    # After completion, both tools should have settled
    snapshot = await budget.snapshot()
    assert snapshot["tool_calls"] == 2


@pytest.mark.asyncio
async def test_completed_receipt_replayed_without_new_approval():
    """Step 2 (receipt lookup) replays without re-approval;
    step 1 (policy DENY) still refuses even with a completed receipt.

    Part A: A completed receipt is replayed without requiring a new
    approval -- the receipt lookup at step 2 short-circuits.

    Part B: If the policy changes to DENY, step 1 refuses before the
    receipt lookup at step 2 is reached.
    """
    registry = ToolRegistry()

    @registry.tool(
        "replay_tool",
        "Idempotent tool.",
        {"type": "object", "properties": {}},
        idempotent=True,
        requires_approval=True,
        risk=ToolRisk.HIGH,
    )
    async def replay_tool(*, state: Any) -> str:
        return json.dumps({"done": True})

    idem_store = InMemoryIdempotencyStore()

    # Write a COMPLETED receipt directly (wrapped in the tool-result envelope)
    key = IdempotencyKey.from_args(RUN_ID, "replay_tool", {})
    await idem_store.save(
        ExecutionAttempt(
            key=key,
            status=AttemptStatus.COMPLETED,
            result=json.dumps({"ok": True, "result": {"replayed": True}}),
        )
    )

    # Part A: ALLOW policy, no approval store needed -- replays from receipt
    cfg_allow = owned_config(
        idempotency_store=idem_store,
        principal=_PRINCIPAL,
        policy=_AllowPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_a", "replay_tool", "{}")],
            registry,
            state=None,
            config=cfg_allow,
        )
        data = json.loads(results[0][1])
        assert data["ok"] is True
        assert data["result"] == {"replayed": True}
    finally:
        await cfg_allow.runtime.close()

    # Part B: Policy changed to DENY -- receipt must NOT be replayed
    cfg_deny = owned_config(
        idempotency_store=idem_store,
        principal=_PRINCIPAL,
        policy=_DenyPolicy(),
    )
    try:
        results = await _execute_tools(
            [("call_b", "replay_tool", "{}")],
            registry,
            state=None,
            config=cfg_deny,
        )
        data = json.loads(results[0][1])
        assert "error" in data, "Expected policy denial despite completed receipt"
    finally:
        await cfg_deny.runtime.close()
