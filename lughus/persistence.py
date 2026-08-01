"""Persistence ports and bounded in-memory reference implementations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from .domain import Run, RunEvent, RunStatus


class ConcurrentUpdateError(RuntimeError):
    pass


@runtime_checkable
class RunStore(Protocol):
    async def create(self, run: Run) -> None: ...
    async def get(self, run_id: str) -> Run | None: ...
    async def update_status(self, run_id: str, expected_version: int, status: RunStatus) -> Run: ...


@runtime_checkable
class EventStore(Protocol):
    async def append(self, event: RunEvent) -> None: ...
    async def read(self, run_id: str, after_sequence: int = -1) -> tuple[RunEvent, ...]: ...


@dataclass(frozen=True, slots=True)
class Checkpoint:
    run_id: str
    version: int
    sequence: int
    state: Mapping[str, Any]
    pending_action: str | None = None
    outcome_unknown: bool = False
    pending_arguments_hash: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(UTC).isoformat())
        if self.version < 0 or self.sequence < 0:
            raise ValueError("Checkpoint versions cannot be negative")


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, checkpoint: Checkpoint, expected_version: int | None) -> None: ...
    async def latest(self, run_id: str) -> Checkpoint | None: ...


@runtime_checkable
class RunUnitOfWork(Protocol):
    async def create_transition(
        self, run: Run, event: RunEvent, checkpoint: Checkpoint
    ) -> None: ...

    async def commit_transition(
        self,
        *,
        run_id: str,
        expected_version: int,
        status: RunStatus,
        event: RunEvent,
        checkpoint: Checkpoint,
    ) -> Run: ...


class InMemoryDurableStore:
    """Atomic in-memory reference store; explicitly not process durable."""

    durable = False
    shared_across_replicas = False
    atomic_updates = True
    supports_idempotency = False
    supports_event_log = True

    def __init__(self, max_runs: int = 10_000, max_events: int = 100_000) -> None:
        if max_runs <= 0 or max_events <= 0:
            raise ValueError("Store capacities must be positive")
        self._max_runs, self._max_events = max_runs, max_events
        self._runs: dict[str, Run] = {}
        self._events: dict[str, list[RunEvent]] = {}
        self._checkpoints: dict[str, Checkpoint] = {}
        self._lock = asyncio.Lock()

    async def create(self, run: Run) -> None:
        async with self._lock:
            if run.run_id in self._runs:
                raise ConcurrentUpdateError("Run already exists")
            if len(self._runs) >= self._max_runs:
                raise RuntimeError("Run store capacity reached")
            self._runs[run.run_id] = run

    async def get(self, run_id: str) -> Run | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def update_status(self, run_id: str, expected_version: int, status: RunStatus) -> Run:
        async with self._lock:
            current = self._runs[run_id]
            if current.version != expected_version:
                raise ConcurrentUpdateError("Run version changed")
            if current.status.terminal:
                raise ConcurrentUpdateError("Terminal runs are immutable")
            updated = replace(current, status=status, version=current.version + 1)
            self._runs[run_id] = updated
            return updated

    async def append(self, event: RunEvent) -> None:
        async with self._lock:
            stream = self._events.setdefault(event.run_id, [])
            if stream and event.sequence <= stream[-1].sequence:
                raise ConcurrentUpdateError("Event sequence is not monotonic")
            if sum(map(len, self._events.values())) >= self._max_events:
                raise RuntimeError("Event store capacity reached")
            stream.append(event)

    async def read(self, run_id: str, after_sequence: int = -1) -> tuple[RunEvent, ...]:
        async with self._lock:
            return tuple(e for e in self._events.get(run_id, ()) if e.sequence > after_sequence)

    async def save(self, checkpoint: Checkpoint, expected_version: int | None) -> None:
        async with self._lock:
            current = self._checkpoints.get(checkpoint.run_id)
            current_version = current.version if current else None
            if current_version != expected_version:
                raise ConcurrentUpdateError("Checkpoint version changed")
            self._checkpoints[checkpoint.run_id] = checkpoint

    async def latest(self, run_id: str) -> Checkpoint | None:
        async with self._lock:
            return self._checkpoints.get(run_id)

    async def create_transition(self, run: Run, event: RunEvent, checkpoint: Checkpoint) -> None:
        async with self._lock:
            if run.run_id in self._runs:
                raise ConcurrentUpdateError("Run already exists")
            if event.run_id != run.run_id or checkpoint.run_id != run.run_id:
                raise ValueError("Transition records must belong to the same run")
            self._runs[run.run_id] = run
            self._events[run.run_id] = [event]
            self._checkpoints[run.run_id] = checkpoint

    async def commit_transition(
        self,
        *,
        run_id: str,
        expected_version: int,
        status: RunStatus,
        event: RunEvent,
        checkpoint: Checkpoint,
    ) -> Run:
        async with self._lock:
            current = self._runs[run_id]
            if current.version != expected_version:
                raise ConcurrentUpdateError("Run version changed")
            if current.status.terminal:
                raise ConcurrentUpdateError("Terminal runs are immutable")
            stream = self._events.setdefault(run_id, [])
            previous_sequence = stream[-1].sequence if stream else -1
            if event.run_id != run_id or event.sequence <= previous_sequence:
                raise ConcurrentUpdateError("Event sequence is not monotonic")
            if checkpoint.run_id != run_id or checkpoint.sequence != event.sequence:
                raise ValueError("Checkpoint must describe the committed event")
            updated = replace(current, status=status, version=current.version + 1)
            self._runs[run_id] = updated
            stream.append(event)
            self._checkpoints[run_id] = checkpoint
            return updated
