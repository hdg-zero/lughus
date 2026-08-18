"""Validated composition root for governed agent execution."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .approval import ApprovalStore
from .budget import BudgetLedger
from .context import ContextItem, ContextManager
from .errors import ApprovalRequiredGroup, RunSuspended
from .event_stream import EventSink
from .idempotency import IdempotencyStore
from .loop import LoopResult, ToolExecutionConfig
from .persistence import CheckpointStore, EventStore, RunStore, RunUnitOfWork
from .policy import Principal, ToolPolicy
from .runtime import ExecutionRuntime
from .tools import ToolRegistry


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


class GovernedAgentRunner:
    """Run through context, budget, policy and transactional state."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    async def run(
        self,
        llm: Any,
        *,
        objective: str,
        principal: Principal,
        registry: ToolRegistry,
        state: Any = None,
        context_items: Sequence[ContextItem] = (),
        max_iterations: int = 20,
        system: str = "You are a helpful assistant.",
    ) -> LoopResult:
        from .budgeted_llm import BudgetedLLM
        from .coordinator import RunCoordinator
        from .domain import EventVisibility, RunEvent, RunStatus
        from .loop import agent_loop
        from .loop._execute import collect_tool_events
        from .persistence import Checkpoint

        # W1-14 / F-04. `context_items` was accepted, typed, and then thrown away.
        # A user supplying context with explicit provenance and trust levels believed
        # their agent received it; it did not. On a framework that sells context
        # governance, a silent lie is the worst possible defect (R7).
        #
        # Proper injection lands in W2-06 (0.11.0) because correct truncation depends
        # on the token budget and atomic message groups (W3-03). Until then this fails
        # loudly: a NotImplementedError is honest, a UserWarning would still be silent
        # in production -- exactly where the user needs to know.
        if context_items:
            raise NotImplementedError(
                "context_items is accepted but not yet injected into the prompt "
                "(tracked as W2-06, shipping in 0.11.0). Until then, fold the content "
                "into `objective` yourself so that nothing is silently dropped."
            )

        if not isinstance(self.runtime.run_store, RunUnitOfWork):
            raise TypeError("AgentRuntime.run_store must implement RunUnitOfWork protocol")
        coordinator = RunCoordinator(self.runtime.run_store)
        run = await coordinator.start(
            objective, tenant_id=principal.tenant_id, principal_id=principal.subject
        )
        running = await coordinator.transition(run, RunStatus.RUNNING, "run.started")
        tool_names = list(registry.names())

        tool_events: list[dict[str, Any]] = []

        def _on_tool_event(event: dict[str, Any]) -> None:
            tool_events.append(event)

        try:
            with collect_tool_events(_on_tool_event):
                result = await agent_loop(
                    BudgetedLLM(llm, self.runtime.budget),
                    system=system,
                    context=objective,
                    registry=registry,
                    tool_names=tool_names,
                    state=state,
                    max_iterations=max_iterations,
                    tool_config=self.runtime.tool_config(run_id=run.run_id, principal=principal),
                )
        except ApprovalRequiredGroup as e:
            # Persist any tool events that completed before the suspension.
            for te in tool_events:
                seq = coordinator.next_sequence(run.run_id)
                run_event = RunEvent(
                    te["type"], run.run_id, seq, te, visibility=EventVisibility.AUDIT
                )
                await self.runtime.event_store.append(run_event)
            # Transition to WAITING — the run is suspended, not failed.
            await coordinator.transition(
                running,
                RunStatus.WAITING,
                "run.waiting",
                {"pending_approvals": [r.request_id for r in e.requests]},
            )
            raise RunSuspended(run.run_id, e.requests) from e
        except BaseException as exc:
            await coordinator.transition(
                running, RunStatus.FAILED, "run.failed", {"error_code": type(exc).__name__}
            )
            raise

        # Persist tool events with globally unique sequences.
        last_event_seq = -1
        for te in tool_events:
            seq = coordinator.next_sequence(run.run_id)
            last_event_seq = seq
            run_event = RunEvent(
                te["type"], run.run_id, seq, te, visibility=EventVisibility.AUDIT
            )
            await self.runtime.event_store.append(run_event)

        # Save a checkpoint capturing post-tool-execution state.
        if tool_events:
            checkpoint = Checkpoint(
                run.run_id,
                running.version,
                last_event_seq,
                {
                    "status": running.status.value,
                    "iterations": result.iterations,
                    "total_tokens": result.total_tokens,
                },
            )
            await self.runtime.checkpoint_store.save(
                checkpoint, expected_version=running.version
            )

        await coordinator.transition(
            running,
            RunStatus.COMPLETED,
            "run.completed",
            {"iterations": result.iterations, "tokens": result.total_tokens},
        )
        return result
