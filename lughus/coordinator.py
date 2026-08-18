"""Transactional run state machine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .domain import EventVisibility, Run, RunEvent, RunStatus
from .persistence import Checkpoint, RunUnitOfWork

_ALLOWED = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.WAITING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    },
    RunStatus.WAITING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
}


class RunCoordinator:
    """Transactional coordinator with per-run sequence allocation."""

    def __init__(self, store: RunUnitOfWork) -> None:
        self.store = store
        self._sequences: dict[str, int] = {}

    def next_sequence(self, run_id: str) -> int:
        """Return the next globally unique sequence for *run_id* and advance the counter."""
        seq = self._sequences.get(run_id, 0)
        self._sequences[run_id] = seq + 1
        return seq

    async def start(
        self, objective: str, *, tenant_id: str, principal_id: str, context_id: str | None = None
    ) -> Run:
        run = Run(objective, context_id=context_id, tenant_id=tenant_id, principal_id=principal_id)
        sequence = self.next_sequence(run.run_id)
        event = RunEvent("run.created", run.run_id, sequence, visibility=EventVisibility.AUDIT)
        checkpoint = Checkpoint(run.run_id, 0, sequence, {"status": run.status.value})
        await self.store.create_transition(run, event, checkpoint)
        return run

    async def transition(
        self,
        run: Run,
        status: RunStatus,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        pending_action: str | None = None,
        pending_arguments_hash: str | None = None,
        outcome_unknown: bool = False,
    ) -> Run:
        allowed = _ALLOWED.get(run.status, set())
        if status not in allowed:
            raise ValueError(f"Invalid run transition: {run.status.value} -> {status.value}")
        sequence = self.next_sequence(run.run_id)
        event = RunEvent(
            event_type, run.run_id, sequence, data or {}, visibility=EventVisibility.AUDIT
        )
        checkpoint = Checkpoint(
            run.run_id,
            run.version + 1,
            sequence,
            {"status": status.value},
            pending_action,
            outcome_unknown,
            pending_arguments_hash=pending_arguments_hash,
        )
        return await self.store.commit_transition(
            run_id=run.run_id,
            expected_version=run.version,
            status=status,
            event=event,
            checkpoint=checkpoint,
        )
