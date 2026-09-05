"""Validated composition root for governed agent execution."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.context import ContextManager
from ..core.event_stream import EventSink
from ..governance.approval import ApprovalStore
from ..governance.budget import BudgetLedger
from ..governance.idempotency import IdempotencyStore
from ..governance.policy import Principal, ToolPolicy
from ..infra.runtime import ExecutionRuntime
from ..loop import ToolExecutionConfig
from ..persistence.store import CheckpointStore, EventStore, RunStore

__all__ = ["AgentRuntime"]


@dataclass(frozen=True, slots=True)
class AgentRuntime:
    """Composition root assembling governance, persistence, and execution infrastructure.

    Provides a centralized, strongly-typed bundle of runtime components needed to
    execute governed agent runs, track event streams, enforce security policies,
    and persist checkpoints across task lifetimes.
    """

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
        """Create a ToolExecutionConfig bound to this runtime's governance and execution services.

        Raises:
            ValueError: If *run_id* is empty or *principal* lacks subject/tenant identification.
        """
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
