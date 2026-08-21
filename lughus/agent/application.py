"""Validated composition root for governed agent execution."""

from __future__ import annotations

from dataclasses import dataclass

from ..governance.approval import ApprovalStore
from ..governance.budget import BudgetLedger
from ..core.context import ContextManager
from ..core.event_stream import EventSink
from ..governance.idempotency import IdempotencyStore
from ..loop import ToolExecutionConfig
from ..persistence.store import CheckpointStore, EventStore, RunStore
from ..governance.policy import Principal, ToolPolicy
from .runner import GovernedAgentRunner  # re-export for backward compatibility
from ..infra.runtime import ExecutionRuntime

# Re-export so ``from lughus.application import GovernedAgentRunner`` still works.
__all__ = ["AgentRuntime", "GovernedAgentRunner"]


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    execution: ExecutionRuntime
    policy: ToolPolicy
    approvals: ApprovalStore
    idempotency: IdempotencyStore
    run_store: RunStore
    event_store: EventStore
    checkpoint_store: CheckpointStore
    events: EventSink
    budget: BudgetLedger
    context: ContextManager

    def tool_config(self, *, run_id: str, principal: Principal) -> ToolExecutionConfig:
        if not run_id or not principal.subject or not principal.tenant_id:
            raise ValueError("A run id and authenticated principal are required")
        return ToolExecutionConfig(
            runtime=self.execution,
            policy=self.policy,
            principal=principal,
            approval_store=self.approvals,
            idempotency_store=self.idempotency,
            budget=self.budget,
            run_id=run_id,
        )
