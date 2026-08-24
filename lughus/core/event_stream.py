"""Event sinks and in-memory subscriptions."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from typing import Protocol

from .domain import RunEvent


class EventSink(Protocol):
    async def append(self, event: RunEvent) -> None: ...


class InMemoryEventSink:
    """Bounded development sink with cursor-based subscriptions.

    Both the event buffer and the per-run sequence tracker are bounded. Once a run
    falls out of the tracker, a sequence regression for that run is no longer
    detected -- acceptable because its events have already been evicted from the
    buffer, and because this sink is explicitly a development tool. Use a durable
    event store in production.
    """

    def __init__(self, max_events: int = 10_000, *, max_tracked_runs: int | None = None) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        if max_tracked_runs is not None and max_tracked_runs <= 0:
            raise ValueError("max_tracked_runs must be positive")
        self._max_events = max_events
        self._events: list[tuple[int, RunEvent]] = []
        # `_events` was bounded but `_last_sequence` was not, so one
        # entry per run_id accumulated for the life of the process. Both structures
        # are now bounded, with a retention aligned on the event bound.
        self._max_tracked_runs = max_tracked_runs or max(64, max_events // 16)
        self._last_sequence: OrderedDict[str, int] = OrderedDict()
        self._global_counter: int = 0
        self._condition = asyncio.Condition()

    async def append(self, event: RunEvent) -> None:
        async with self._condition:
            previous = self._last_sequence.get(event.run_id, -1)
            if event.sequence <= previous:
                raise ValueError("Event sequences must be strictly increasing per run")
            global_offset = self._global_counter
            self._global_counter += 1
            self._events.append((global_offset, event))
            self._last_sequence[event.run_id] = event.sequence
            self._last_sequence.move_to_end(event.run_id)
            while len(self._last_sequence) > self._max_tracked_runs:
                # Dropping the least recently seen run only loses the ability to
                # detect a sequence regression for a run whose events have already
                # left `_events`. Documented on the class: this is a development sink.
                self._last_sequence.popitem(last=False)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
            self._condition.notify_all()

    def snapshot(self, run_id: str | None = None) -> tuple[RunEvent, ...]:
        return tuple(e for _, e in self._events if run_id is None or e.run_id == run_id)

    async def subscribe(
        self, after_sequence: int = -1, *, run_id: str | None = None
    ) -> AsyncIterator[RunEvent]:
        cursor = after_sequence
        while True:
            async with self._condition:

                def _has_new_events(c: int = cursor) -> bool:
                    if run_id is not None:
                        return any(e.sequence > c and e.run_id == run_id for _, e in self._events)
                    return any(offset > c for offset, _ in self._events)

                await self._condition.wait_for(_has_new_events)
                if run_id is not None:
                    pending = tuple(
                        (offset, e)
                        for offset, e in self._events
                        if e.sequence > cursor and e.run_id == run_id
                    )
                else:
                    pending = tuple((offset, e) for offset, e in self._events if offset > cursor)
            for offset, event in pending:
                cursor = event.sequence if run_id is not None else offset
                yield event
