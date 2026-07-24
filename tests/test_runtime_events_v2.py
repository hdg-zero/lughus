import asyncio

import pytest

from lughus.domain import EventVisibility, Run, RunEvent, RunStatus
from lughus.event_stream import InMemoryEventSink
from lughus.runtime import ExecutionRuntime, RuntimeConfig


def test_run_event_round_trip_and_terminal_status():
    run = Run("objective")
    event = RunEvent("run.started", run.run_id, 0, visibility=EventVisibility.PUBLIC)
    assert RunEvent.from_dict(event.to_dict()) == event
    assert RunStatus.COMPLETED.terminal
    assert not RunStatus.RUNNING.terminal


@pytest.mark.asyncio
async def test_event_sink_requires_monotonic_sequences():
    sink = InMemoryEventSink()
    await sink.append(RunEvent("run.started", "run_1", 0))
    with pytest.raises(ValueError, match="strictly increasing"):
        await sink.append(RunEvent("duplicate", "run_1", 0))


@pytest.mark.asyncio
async def test_execution_runtime_bounds_tools_and_closes():
    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=1, max_sync_workers=1))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first():
        async with runtime.tool_slot():
            entered.set()
            await release.wait()

    task = asyncio.create_task(first())
    await entered.wait()
    with pytest.raises(Exception, match="slot"):
        async with runtime.tool_slot(timeout=0):
            pass
    release.set()
    await task
    assert await runtime.run_sync(lambda: 42) == 42
    await runtime.close()
    with pytest.raises(RuntimeError, match="closed"):
        async with runtime.tool_slot():
            pass
