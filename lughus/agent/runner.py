"""One lifecycle and governance pipeline for blocking and streamed execution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing, suppress
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

from ..core._defaults import DEFAULT_MAX_ITERATIONS
from ..core.context import ContextItem, TrustLevel
from ..core.domain import EventVisibility, Run, RunEvent, RunStatus, canonical_hash
from ..core.errors import ApprovalRequiredGroup, RunSuspended
from ..core.event_stream import EventSink, InMemoryEventSink
from ..governance.budgeted_llm import BudgetedLLM
from ..loop import LoopResult, agent_loop, agent_loop_stream
from ..persistence.coordinator import RunCoordinator
from ..persistence.execution import ExecutionJournal, JournalBudget, LoopCheckpoint, OutcomeUnknown
from ..persistence.store import RunUnitOfWork
from .application import AgentRuntime


class GovernedAgentRunner:
    """Own run lifecycle, not infrastructure. The supplied runtime is caller-owned.

    Both entry points enforce the same identity, policy, approval and budget
    configuration. Streaming uses a bounded queue; closing the iterator cancels
    its producer. Public text deltas are provisional, not persisted checkpoints.
    """

    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        *,
        event_sink: EventSink | None = None,
        stream_buffer: int = 64,
    ) -> None:
        if stream_buffer <= 0:
            raise ValueError("stream_buffer must be positive")
        self.runtime = runtime
        self.events = (
            event_sink
            if event_sink is not None
            else (runtime.events if runtime is not None else InMemoryEventSink())
        )
        self.stream_buffer = stream_buffer

    async def run(self, llm: Any, **kwargs: Any) -> LoopResult:
        return await self._execute(llm, streaming=False, deliver=None, **kwargs)

    async def resume(self, run_id: str, llm: Any, *, principal: Any, registry: Any) -> LoopResult:
        """Resume the recorded objective, history and tool manifest under current policy."""
        if self.runtime is None or self.runtime.journal is None:
            raise ValueError("Resumption requires a durable execution journal")
        return await self._execute(
            llm,
            streaming=False,
            deliver=None,
            _resume_run_id=run_id,
            principal=principal,
            registry=registry,
        )

    def resume_stream(
        self, run_id: str, llm: Any, *, principal: Any, registry: Any
    ) -> AsyncIterator[RunEvent]:
        if self.runtime is None or self.runtime.journal is None:
            raise ValueError("Resumption requires a durable execution journal")
        return self.stream(llm, _resume_run_id=run_id, principal=principal, registry=registry)

    async def stream(
        self,
        llm: Any,
        *,
        streaming_mode: str = "live",
        **kwargs: Any,
    ) -> AsyncIterator[RunEvent]:
        queue: asyncio.Queue[RunEvent | None] = asyncio.Queue(self.stream_buffer)

        async def produce() -> LoopResult:
            try:
                return await self._execute(
                    llm,
                    streaming=True,
                    deliver=queue.put,
                    streaming_mode=streaming_mode,
                    **kwargs,
                )
            finally:
                # On consumer cancellation nobody remains to drain a full queue.
                task = asyncio.current_task()
                if task is None or not task.cancelling():
                    await queue.put(None)

        producer = asyncio.create_task(produce(), name="lughus-run")
        try:
            while (event := await queue.get()) is not None:
                yield event
            await producer  # propagate provider failures and RunSuspended
        finally:
            if not producer.done():
                producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

    async def _execute(
        self,
        llm: Any,
        *,
        streaming: bool,
        deliver: Callable[[RunEvent | None], Awaitable[None]] | None,
        streaming_mode: str = "live",
        **kwargs: Any,
    ) -> LoopResult:
        rt = self.runtime
        coordinator: RunCoordinator | None = None
        lock = asyncio.Lock()
        sequence = 0
        resume_id = kwargs.pop("_resume_run_id", None)
        journal: ExecutionJournal | None = None
        saved: dict[str, Any] | None = None
        if rt is not None:
            forbidden = {"tool_config", "context", "tools"} & kwargs.keys()
            if forbidden:
                raise ValueError(f"Governed execution owns these arguments: {sorted(forbidden)}")
            principal = kwargs.pop("principal", None)
            objective = kwargs.pop("objective", "")
            if principal is None or not principal.subject or not principal.tenant_id:
                raise ValueError("An authenticated principal is required")
            if "registry" not in kwargs:
                raise ValueError("Governed execution requires a registry")
            if not isinstance(rt.run_store, RunUnitOfWork):
                raise TypeError("run_store must implement RunUnitOfWork")
            coordinator = RunCoordinator(rt.run_store)
            if resume_id is not None:
                if rt.journal is None:
                    raise ValueError("No durable journal configured")
                existing = await rt.run_store.get(resume_id)
                if (
                    existing is None
                    or existing.tenant_id != principal.tenant_id
                    or existing.principal_id != principal.subject
                ):
                    raise PermissionError("Run is unavailable to this principal")
                if existing.status not in {RunStatus.RUNNING, RunStatus.WAITING}:
                    raise ValueError("Only interrupted or waiting runs may resume")
                run = existing
                objective = run.objective
            else:
                run = await coordinator.start(
                    objective,
                    tenant_id=principal.tenant_id,
                    principal_id=principal.subject,
                )
            kwargs["context"] = objective
            kwargs.setdefault("system", "You are a helpful assistant.")
            kwargs["context_items"] = rt.context.select(kwargs.get("context_items", ())).items
            kwargs["tool_config"] = rt.tool_config(run_id=run.run_id, principal=principal)
            ledger = rt.budget
            if rt.journal is not None:
                registry = kwargs["registry"]
                if kwargs.get("state") is not None:
                    raise ValueError("Durable execution does not accept mutable injected state")
                # Persisted execution must not depend on mutable in-process tool state.
                if any(registry.get_tool(name).takes_state for name in registry.names()):
                    raise ValueError(
                        "Durable tools must not accept injected state; use explicit typed arguments"
                    )
                manifest = canonical_hash(
                    [
                        {
                            "name": name,
                            "version": registry.get_tool(name).version,
                            "schema": registry.get_tool(name).parameters_schema,
                            "description": registry.get_tool(name).description,
                            "concurrency": registry.get_tool(name).concurrency.value,
                            "idempotent": registry.get_tool(name).idempotent,
                            "output_schema": registry.get_tool(name).output_schema,
                            "effects": sorted(registry.get_tool(name).effects),
                            "scopes": sorted(registry.get_tool(name).required_scopes),
                            "approval": registry.get_tool(name).requires_approval,
                            "risk": registry.get_tool(name).risk.value,
                        }
                        for name in sorted(registry.names())
                    ]
                )
                owner = uuid4().hex
                snapshot = (
                    None
                    if resume_id
                    else {
                        "schema_version": 1,
                        "manifest": manifest,
                        "model": llm.model,
                        "system": kwargs["system"],
                        "tool_names": kwargs.get("tool_names"),
                        "context_items": [asdict(item) for item in kwargs["context_items"]],
                        "max_iterations": kwargs.get("max_iterations", DEFAULT_MAX_ITERATIONS),
                        "loop": LoopCheckpoint().to_dict(),
                    }
                )
                saved = await rt.journal.open_execution(run.run_id, owner, snapshot)
                journal = ExecutionJournal(rt.journal, run.run_id, owner)
                try:
                    if (
                        saved.get("schema_version") != 1
                        or saved["manifest"] != manifest
                        or saved["model"] != llm.model
                    ):
                        raise ValueError(
                            "Recorded schema, model or tool manifest changed; migration is explicit"
                        )
                    kwargs["system"] = saved["system"]
                    kwargs["context_items"] = [
                        ContextItem(**{**item, "trust": TrustLevel(item["trust"])})
                        for item in saved["context_items"]
                    ]
                    kwargs["tool_names"] = saved["tool_names"]
                    kwargs["max_iterations"] = saved["max_iterations"]
                    ledger = JournalBudget(
                        rt.budget.limit, journal, await rt.journal.budget(run.run_id, owner)
                    )

                    async def checkpoint(value: LoopCheckpoint) -> None:
                        assert saved is not None and journal is not None
                        saved["loop"] = value.to_dict()
                        await journal.store.snapshot_execution(run.run_id, journal.owner, saved)

                    kwargs["tool_config"] = replace(
                        kwargs["tool_config"],
                        journal=journal,
                        idempotency_store=None,
                        budget=ledger,
                        loop_state=LoopCheckpoint(**saved["loop"]),
                        on_checkpoint=checkpoint,
                    )
                except BaseException:
                    await rt.journal.release_execution(run.run_id, owner)
                    raise
            llm = BudgetedLLM(llm, ledger)
        else:
            run = Run(objective=kwargs.get("context") or "agent run", status=RunStatus.RUNNING)

        async def emit(
            kind: str,
            data: dict[str, Any],
            *,
            audit: bool = False,
            terminal: RunStatus | None = None,
        ) -> None:
            nonlocal sequence, run
            async with lock:
                if coordinator is not None:
                    if terminal is not None:
                        run = await coordinator.transition(run, terminal, kind, data)
                        assert rt is not None
                        checkpoint = await rt.checkpoint_store.latest(run.run_id)
                        if checkpoint is None:
                            raise RuntimeError("Committed run checkpoint is missing")
                        seq = checkpoint.sequence
                    else:
                        seq = coordinator.next_sequence(run.run_id)
                else:
                    seq, sequence = sequence, sequence + 1
                event = RunEvent(
                    kind,
                    run.run_id,
                    seq,
                    data,
                    visibility=EventVisibility.AUDIT if audit else EventVisibility.PUBLIC,
                )
                if rt is not None and terminal is None:
                    await rt.event_store.append(event)
                if self.events is not (rt.event_store if rt else None):
                    await self.events.append(event)
                if deliver is not None:
                    await deliver(event)

        async def tool_event(event: dict[str, Any]) -> None:
            await emit(str(event["type"]), event, audit=True)

        if rt is not None:
            kwargs["tool_config"] = replace(kwargs["tool_config"], on_tool_event=tool_event)
        try:
            await emit(
                "run.resumed" if resume_id else "run.started",
                {},
                terminal=RunStatus.RUNNING if rt else None,
            )
            result: LoopResult | None = None
            if streaming:
                async with aclosing(
                    agent_loop_stream(
                        llm,
                        streaming_mode=streaming_mode,
                        **kwargs,
                    )
                ) as stream:
                    async for item in stream:
                        if isinstance(item, LoopResult):
                            result = item
                        else:
                            await emit("text.delta", {"delta": item.content})
            else:
                result = await agent_loop(llm, **kwargs)
            if result is None:
                raise RuntimeError("Agent stream ended without a final result")
            await emit(
                "run.completed",
                {
                    "text": str(result),
                    "iterations": result.iterations,
                    "tokens": result.total_tokens,
                },
                terminal=RunStatus.COMPLETED,
            )
            return result
        except ApprovalRequiredGroup as exc:
            await emit(
                "run.waiting",
                {"pending_approvals": [request.request_id for request in exc.requests]},
                terminal=RunStatus.WAITING,
            )
            raise RunSuspended(run.run_id, exc.requests) from exc
        except OutcomeUnknown as exc:
            await emit(
                "run.reconciliation_required", {"call_id": exc.call_id}, terminal=RunStatus.WAITING
            )
            raise
        except asyncio.CancelledError:
            # Persist cancellation without blocking on an abandoned stream queue.
            deliver = None
            if not run.status.terminal:
                await emit(
                    "run.interrupted" if journal else "run.cancelled",
                    {},
                    terminal=RunStatus.WAITING if journal else RunStatus.CANCELLED,
                )
            raise
        except Exception as exc:
            if journal is not None and not run.status.terminal:
                unresolved = await journal.store.unresolved_action(run.run_id, journal.owner)
                if unresolved is not None:
                    await emit(
                        "run.reconciliation_required",
                        {"call_id": unresolved},
                        terminal=RunStatus.WAITING,
                    )
                    raise OutcomeUnknown(run.run_id, unresolved) from exc
            if not run.status.terminal:
                await emit(
                    "run.failed", {"error_code": type(exc).__name__}, terminal=RunStatus.FAILED
                )
            raise
        finally:
            if journal is not None:
                await journal.store.release_execution(run.run_id, journal.owner)
