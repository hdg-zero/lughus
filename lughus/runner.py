"""Event-oriented compatibility runner."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .domain import EventVisibility, Run, RunEvent, RunStatus
from .event_stream import EventSink, InMemoryEventSink
from .loop import LoopResult, agent_loop, agent_loop_stream


class AgentRunner:
    def __init__(self, event_sink: EventSink | None = None) -> None:
        self.events = event_sink or InMemoryEventSink()

    async def run(self, llm: Any, **kwargs: Any) -> LoopResult:
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

    async def stream(
        self, llm: Any, *, streaming_mode: str = "live", **kwargs: Any
    ) -> AsyncIterator[RunEvent]:
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
