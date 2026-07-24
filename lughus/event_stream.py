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
        self._condition = asyncio.Condition()

    async def append(self, event: RunEvent) -> None:
        async with self._condition:
            if self._events and event.sequence <= self._events[-1].sequence:
                raise ValueError("Event sequences must be strictly increasing")
            self._events.append(event)
            if len(self._events) > self._max_events:
                del self._events[: len(self._events) - self._max_events]
            self._condition.notify_all()

    def snapshot(self, run_id: str | None = None) -> tuple[RunEvent, ...]:
        return tuple(e for e in self._events if run_id is None or e.run_id == run_id)

    async def subscribe(self, after_sequence: int = -1) -> AsyncIterator[RunEvent]:
        cursor = after_sequence
        while True:
            async with self._condition:
                await self._condition.wait_for(
                    lambda: any(e.sequence > cursor for e in self._events)
                )
                pending = tuple(e for e in self._events if e.sequence > cursor)
            for event in pending:
                cursor = event.sequence
                yield event
