"""Event-oriented unified runner with optional governance."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

from .domain import EventVisibility, Run, RunEvent, RunStatus
from .event_stream import EventSink, InMemoryEventSink
from .loop import LoopResult, agent_loop, agent_loop_stream

if TYPE_CHECKING:
    from .context import ContextItem
    from .policy import Principal
    from .tools import ToolRegistry


class GovernedAgentRunner:
    """Unified runner with optional governance.

    Without an *AgentRuntime* the runner wraps :func:`agent_loop` /
    :func:`agent_loop_stream` with lightweight event emission — identical
    behaviour to the legacy ``AgentRunner``.

    With an *AgentRuntime* the full governance pipeline is applied:
    run coordination, budget tracking, policy enforcement, approval gates,
    idempotent execution, tool-event persistence and checkpointing.
    """

    def __init__(
        self,
        runtime: Any = None,
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        self.runtime = runtime
        if event_sink is not None:
            self.events = event_sink
        elif runtime is not None:
            self.events = runtime.events
        else:
            self.events = InMemoryEventSink()

    # ── public API ───────────────────────────────────────────────────

    async def run(self, llm: Any, **kwargs: Any) -> LoopResult:
        """Execute an agent loop, optionally governed.

        When *self.runtime* is ``None`` all keyword arguments are forwarded
        directly to :func:`agent_loop`.  When a runtime is present the
        governed path is taken and the caller must supply *objective*,
        *principal* and *registry* at minimum.
        """
        if self.runtime is not None:
            return await self._governed_run(llm, **kwargs)
        return await self._simple_run(llm, **kwargs)

    async def stream(
        self, llm: Any, *, streaming_mode: str = "live", **kwargs: Any
    ) -> AsyncIterator[RunEvent]:
        """Stream agent loop events (ungoverned path only)."""
        run = Run(objective=kwargs.get("context", "agent run"), status=RunStatus.RUNNING)
        sequence = 0
        event = RunEvent("run.started", run.run_id, sequence, visibility=EventVisibility.PUBLIC)
        await self.events.append(event)
        yield event
        try:
            async for item in agent_loop_stream(llm, streaming_mode=streaming_mode, **kwargs):
                sequence += 1
                if isinstance(item, LoopResult):
                    event = RunEvent(
                        "run.completed",
                        run.run_id,
                        sequence,
                        {"text": str(item), "iterations": item.iterations},
                        visibility=EventVisibility.PUBLIC,
                    )
                else:
                    event = RunEvent(
                        "text.delta",
                        run.run_id,
                        sequence,
                        {"delta": item.content},
                        visibility=EventVisibility.PUBLIC,
                    )
                await self.events.append(event)
                yield event
        except BaseException as exc:
            sequence += 1
            event = RunEvent(
                "run.failed",
                run.run_id,
                sequence,
                {"error_code": type(exc).__name__},
                visibility=EventVisibility.PUBLIC,
            )
            await self.events.append(event)
            yield event
            raise

    # ── simple (ungoverned) path ─────────────────────────────────────

    async def _simple_run(self, llm: Any, **kwargs: Any) -> LoopResult:
        run = Run(objective=kwargs.get("context", "agent run"), status=RunStatus.RUNNING)
        sequence = 0
        await self.events.append(RunEvent("run.started", run.run_id, sequence))
        try:
            result = await agent_loop(llm, **kwargs)
        except BaseException as exc:
            await self.events.append(
                RunEvent(
                    "run.failed",
                    run.run_id,
                    sequence + 1,
                    {"error_code": type(exc).__name__},
                    visibility=EventVisibility.INTERNAL,
                )
            )
            raise
        await self.events.append(
            RunEvent(
                "run.completed",
                run.run_id,
                sequence + 1,
                {"text": str(result), "iterations": result.iterations},
                visibility=EventVisibility.PUBLIC,
            )
        )
        return result

    # ── governed path ────────────────────────────────────────────────

    async def _governed_run(
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
        from .errors import ApprovalRequiredGroup, RunSuspended
        from .loop._execute import collect_tool_events
        from .persistence import Checkpoint, RunUnitOfWork

        rt = self.runtime
        if not isinstance(rt.run_store, RunUnitOfWork):
            raise TypeError("AgentRuntime.run_store must implement RunUnitOfWork protocol")
        coordinator = RunCoordinator(rt.run_store)
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
                    BudgetedLLM(llm, rt.budget),
                    system=system,
                    context=objective,
                    registry=registry,
                    tool_names=tool_names,
                    state=state,
                    max_iterations=max_iterations,
                    tool_config=rt.tool_config(run_id=run.run_id, principal=principal),
                    context_items=context_items,
                )
        except ApprovalRequiredGroup as e:
            # Persist any tool events that completed before the suspension.
            for te in tool_events:
                seq = coordinator.next_sequence(run.run_id)
                run_event = RunEvent(
                    te["type"], run.run_id, seq, te, visibility=EventVisibility.AUDIT
                )
                await rt.event_store.append(run_event)
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
            run_event = RunEvent(te["type"], run.run_id, seq, te, visibility=EventVisibility.AUDIT)
            await rt.event_store.append(run_event)

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
            await rt.checkpoint_store.save(checkpoint, expected_version=running.version)

        await coordinator.transition(
            running,
            RunStatus.COMPLETED,
            "run.completed",
            {"iterations": result.iterations, "tokens": result.total_tokens},
        )
        return result


# Backward-compatible alias — the old AgentRunner is now GovernedAgentRunner
# with governance disabled (runtime=None).
AgentRunner = GovernedAgentRunner
