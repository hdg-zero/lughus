"""Integration tests: approval barriers suspend runs instead of leaking to the model.

When a tool requires approval and none exists, the framework must raise
ApprovalRequired (NOT SafeToolError).  The model never sees "approval_required"
in its tool results.  The governed runner catches ApprovalRequiredGroup,
transitions the run to WAITING, and raises RunSuspended.
"""

from __future__ import annotations

import json
from dataclasses import replace as _dc_replace
from typing import Any

import pytest

from lughus.agent.application import AgentRuntime, GovernedAgentRunner
from lughus.core.context import ContextManager
from lughus.core.errors import RunSuspended
from lughus.core.event_stream import InMemoryEventSink
from lughus.engine.tools import ToolRegistry
from lughus.governance.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
)
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.governance.idempotency import InMemoryIdempotencyStore
from lughus.governance.policy import AllowAllPolicy, Principal
from lughus.infra.runtime import ExecutionRuntime
from lughus.persistence import InMemoryRunStore
from lughus.testing import MockLLM

_PRINCIPAL = Principal(subject="tester", tenant_id="test-tenant")
_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


# ── Helper stores ────────────────────────────────────────


class _PreApprovedStore(InMemoryApprovalStore):
    """Approval store where ``find()`` always returns an approved request."""

    async def find(self, run_id: str, proposal_hash: str) -> ApprovalRequest | None:
        return _dc_replace(
            ApprovalRequest(
                run_id=run_id,
                tool_name="restricted",
                proposal_hash=proposal_hash,
                risk="low",
            ),
            status=ApprovalStatus.APPROVED,
            decided_by="reviewer",
        )

    async def consume(self, request_id: str) -> ApprovalRequest:
        # No-op for synthetic requests not backed by real store entries.
        return ApprovalRequest(run_id="", tool_name="restricted", proposal_hash="", risk="low")


class _PreRejectedStore(InMemoryApprovalStore):
    """Approval store where ``find()`` always returns a rejected request."""

    async def find(self, run_id: str, proposal_hash: str) -> ApprovalRequest | None:
        return _dc_replace(
            ApprovalRequest(
                run_id=run_id,
                tool_name="restricted",
                proposal_hash=proposal_hash,
                risk="low",
            ),
            status=ApprovalStatus.REJECTED,
            decided_by="reviewer",
        )


# ── Helpers ──────────────────────────────────────────────


def _build_runtime(
    approval_store: InMemoryApprovalStore | None = None,
) -> tuple[AgentRuntime, InMemoryRunStore]:
    """Build a minimal AgentRuntime with all governance components."""
    store = InMemoryRunStore()
    return (
        AgentRuntime(
            execution=ExecutionRuntime(),
            policy=AllowAllPolicy(),
            approvals=approval_store if approval_store is not None else InMemoryApprovalStore(),
            idempotency=InMemoryIdempotencyStore(),
            run_store=store,
            event_store=store,
            checkpoint_store=store,
            events=InMemoryEventSink(),
            budget=BudgetLedger(BudgetLimit(tool_calls=100)),
            context=ContextManager(max_characters=100_000),
        ),
        store,
    )


# ── Tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_never_sees_approval_required() -> None:
    """The model (MockLLM) must never receive a tool result containing
    'approval_required'.  The run must be suspended instead."""
    runtime, _store = _build_runtime()
    registry = ToolRegistry()

    @registry.tool("restricted", "Restricted action", _EMPTY_SCHEMA, requires_approval=True)
    async def restricted(*, state: Any) -> str:
        return "done"

    llm = MockLLM(
        [
            [{"name": "restricted", "arguments": {}, "id": "call_1"}],
            "Done!",
        ]
    )
    runner = GovernedAgentRunner(runtime)

    with pytest.raises(RunSuspended):
        await runner.run(
            llm,
            objective="do something restricted",
            principal=_PRINCIPAL,
            registry=registry,
            system="You are a test assistant.",
        )

    # The LLM should only have been called once (the initial call that
    # produced the tool call).  It must NOT have received a second call
    # with "approval_required" in a tool result.
    assert len(llm.calls) == 1
    # Verify no tool result message contains "approval_required"
    for call in llm.calls:
        for msg in call["messages"]:
            if msg.get("role") == "tool":
                assert "approval_required" not in msg.get("content", "")

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_run_ends_in_waiting() -> None:
    """A run requiring unapproved tools transitions to WAITING status."""
    runtime, store = _build_runtime()
    registry = ToolRegistry()

    @registry.tool("restricted", "Restricted action", _EMPTY_SCHEMA, requires_approval=True)
    async def restricted(*, state: Any) -> str:
        return "done"

    llm = MockLLM(
        [
            [{"name": "restricted", "arguments": {}, "id": "call_1"}],
            "Done!",
        ]
    )
    runner = GovernedAgentRunner(runtime)

    with pytest.raises(RunSuspended):
        await runner.run(
            llm,
            objective="do something restricted",
            principal=_PRINCIPAL,
            registry=registry,
            system="You are a test assistant.",
        )

    # Find the run and verify its final status is WAITING
    for run_id in store._runs:
        events = await store.read(run_id)
        event_types = [e.type for e in events]
        assert "run.waiting" in event_types
        # Must NOT have run.failed or run.completed
        assert "run.failed" not in event_types
        assert "run.completed" not in event_types

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_two_tools_produce_single_suspension() -> None:
    """Two tools both requiring approval produce one RunSuspended with two
    pending requests."""
    runtime, _store = _build_runtime()
    registry = ToolRegistry()

    @registry.tool("tool_a", "Tool A", _EMPTY_SCHEMA, requires_approval=True)
    async def tool_a(*, state: Any) -> str:
        return "a"

    @registry.tool("tool_b", "Tool B", _EMPTY_SCHEMA, requires_approval=True)
    async def tool_b(*, state: Any) -> str:
        return "b"

    llm = MockLLM(
        [
            [
                {"name": "tool_a", "arguments": {}, "id": "call_a"},
                {"name": "tool_b", "arguments": {}, "id": "call_b"},
            ],
            "Done!",
        ]
    )
    runner = GovernedAgentRunner(runtime)

    with pytest.raises(RunSuspended) as exc_info:
        await runner.run(
            llm,
            objective="do two restricted things",
            principal=_PRINCIPAL,
            registry=registry,
            system="You are a test assistant.",
        )

    suspended = exc_info.value
    assert len(suspended.pending_requests) == 2
    tool_names = {r.tool_name for r in suspended.pending_requests}
    assert tool_names == {"tool_a", "tool_b"}

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_approved_then_resumed() -> None:
    """Pre-approved tool runs to completion normally (happy path)."""
    runtime, _run_store = _build_runtime(approval_store=_PreApprovedStore())
    registry = ToolRegistry()

    @registry.tool("restricted", "Restricted action", _EMPTY_SCHEMA, requires_approval=True)
    async def restricted(*, state: Any) -> str:
        return "done"

    llm = MockLLM(
        [
            [{"name": "restricted", "arguments": {}, "id": "call_1"}],
            "Done!",
        ]
    )
    runner = GovernedAgentRunner(runtime)

    result = await runner.run(
        llm,
        objective="do something restricted",
        principal=_PRINCIPAL,
        registry=registry,
        system="You are a test assistant.",
    )

    assert "Done" in str(result)
    await runtime.execution.close()


@pytest.mark.asyncio
async def test_rejected_produces_failure() -> None:
    """Pre-rejected tool causes the run to see a ToolExecutionError payload
    (rejection IS a tool error visible to the model, unlike approval barriers)."""
    runtime, _store = _build_runtime(approval_store=_PreRejectedStore())
    registry = ToolRegistry()

    @registry.tool("restricted", "Restricted action", _EMPTY_SCHEMA, requires_approval=True)
    async def restricted(*, state: Any) -> str:
        return "done"

    # The LLM requests the restricted tool. The rejection should produce
    # an error payload that the model sees (rejection IS a tool error).
    # The run completes because the error is converted to a tool error
    # payload and the LLM gets a second turn.
    llm = MockLLM(
        [
            [{"name": "restricted", "arguments": {}, "id": "call_1"}],
            "The tool was rejected.",
        ]
    )
    runner = GovernedAgentRunner(runtime)

    result = await runner.run(
        llm,
        objective="do something restricted",
        principal=_PRINCIPAL,
        registry=registry,
        system="You are a test assistant.",
    )

    # The model receives the rejection error and responds
    assert "rejected" in str(result).lower()

    # Verify the model received an error payload with the rejection
    assert len(llm.calls) == 2
    second_call_messages = llm.calls[1]["messages"]
    tool_results = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_results) == 1
    error_data = json.loads(tool_results[0]["content"])
    assert "error" in error_data

    await runtime.execution.close()
