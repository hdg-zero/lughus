"""Event sinks and in-memory subscriptions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from .domain import RunEvent


class EventSink(Protocol):
    async def append(self, event: RunEvent) -> None: ...


class InMemoryEventSink:
    """Bounded development sink with cursor-based subscriptions."""

    def __init__(self, max_events: int = 10_000) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._max_events = max_events
        self._events: list[RunEvent] = []
        self._last_sequence: dict[str, int] = {}
        self._condition = asyncio.Condition()

    async def append(self, event: RunEvent) -> None:
        async with self._condition:
            previous = self._last_sequence.get(event.run_id, -1)
            if event.sequence <= previous:
                raise ValueError("Event sequences must be strictly increasing per run")
            self._events.append(event)
            self._last_sequence[event.run_id] = event.sequence
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
            self._condition.notify_all()

    def snapshot(self, run_id: str | None = None) -> tuple[RunEvent, ...]:
        return tuple(e for e in self._events if run_id is None or e.run_id == run_id)

    async def subscribe(
        self, after_sequence: int = -1, *, run_id: str | None = None
    ) -> AsyncIterator[RunEvent]:
        cursor = after_sequence
        while True:
            async with self._condition:

                def _has_new_events(c: int = cursor) -> bool:
                    return any(
                        e.sequence > c and (run_id is None or e.run_id == run_id)
                        for e in self._events
                    )

                await self._condition.wait_for(_has_new_events)
                pending = tuple(
                    e for e in self._events
                    if e.sequence > cursor and (run_id is None or e.run_id == run_id)
                )
            for event in pending:
                cursor = event.sequence
                yield event
