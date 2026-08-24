import asyncio

import pytest

from lughus.core.domain import EventVisibility, Run, RunEvent, RunStatus
from lughus.core.event_stream import InMemoryEventSink
from lughus.infra.runtime import ExecutionRuntime, RuntimeConfig


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


def test_runtime_config_validation():
    with pytest.raises(ValueError, match="positive"):
        RuntimeConfig(max_global_tools=0)
    with pytest.raises(ValueError, match="positive"):
        RuntimeConfig(max_sync_workers=0)
    with pytest.raises(ValueError, match="negative"):
        RuntimeConfig(queue_timeout=-1.0)


@pytest.mark.asyncio
async def test_execution_runtime_async_context_manager():
    async with ExecutionRuntime(RuntimeConfig(max_global_tools=2)) as runtime:
        assert await runtime.run_sync(lambda: "ok") == "ok"
    with pytest.raises(RuntimeError, match="closed"):
        async with runtime.tool_slot():
            pass


@pytest.mark.asyncio
async def test_execution_runtime_idempotent_close():
    runtime = ExecutionRuntime()
    await runtime.close()
    await runtime.close()  # No-op


@pytest.mark.asyncio
async def test_execution_runtime_tool_slot_timeout():
    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=1))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def block():
        async with runtime.tool_slot():
            entered.set()
            await release.wait()

    task = asyncio.create_task(block())
    await entered.wait()

    with pytest.raises(Exception, match="Timed out waiting for a global tool slot"):
        async with runtime.tool_slot(timeout=0.01):
            pass

    release.set()
    await task
    await runtime.close()


def test_event_sink_max_events_validation():
    with pytest.raises(ValueError, match="positive"):
        InMemoryEventSink(max_events=0)


@pytest.mark.asyncio
async def test_event_sink_snapshot_and_truncation():
    sink = InMemoryEventSink(max_events=2)
    e1 = RunEvent("run.started", "run_1", 0)
    e2 = RunEvent("text.delta", "run_1", 1)
    e3 = RunEvent("run.completed", "run_1", 2)

    await sink.append(e1)
    await sink.append(e2)
    await sink.append(e3)

    # Should be truncated to last 2 events
    snaps = sink.snapshot("run_1")
    assert len(snaps) == 2
    assert snaps[0] == e2
    assert snaps[1] == e3

    # Snapshot filtering by run_id
    assert sink.snapshot("run_2") == ()


@pytest.mark.asyncio
async def test_event_sink_subscribe():
    sink = InMemoryEventSink()
    e1 = RunEvent("run.started", "r1", 0)
    e2 = RunEvent("run.completed", "r1", 1)

    received: list[RunEvent] = []

    async def subscriber():
        async for evt in sink.subscribe():
            received.append(evt)
            if evt.type == "run.completed":
                break

    sub_task = asyncio.create_task(subscriber())
    await asyncio.sleep(0.01)
    await sink.append(e1)
    await sink.append(e2)

    await asyncio.wait_for(sub_task, timeout=1.0)
    assert received == [e1, e2]


@pytest.mark.asyncio
async def test_agent_runner_run_success():
    from lughus.agent.runner import GovernedAgentRunner
    from lughus.engine.tools import ToolRegistry
    from lughus.testing import MockLLM

    llm = MockLLM(["Hello from runner"])
    registry = ToolRegistry()
    runner = GovernedAgentRunner()

    res = await runner.run(llm, system=".", context="Hi", registry=registry, tool_names=[])
    assert res == "Hello from runner"

    events = runner.events.snapshot()
    assert len(events) == 2
    assert events[0].type == "run.started"
    assert events[1].type == "run.completed"
    assert events[1].data["text"] == "Hello from runner"


@pytest.mark.asyncio
async def test_agent_runner_run_failure():
    from lughus.agent.runner import GovernedAgentRunner
    from lughus.engine.tools import ToolRegistry

    class BrokenLLM:
        model = "broken"

        async def generate(self, **_):
            raise RuntimeError("LLM failure")

    runner = GovernedAgentRunner()
    registry = ToolRegistry()
    with pytest.raises(RuntimeError, match="LLM failure"):
        await runner.run(BrokenLLM(), system=".", context="Hi", registry=registry, tool_names=[])

    events = runner.events.snapshot()
    assert len(events) == 2
    assert events[0].type == "run.started"
    assert events[1].type == "run.failed"
    assert events[1].data["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_agent_runner_stream_success():
    from lughus.agent.runner import GovernedAgentRunner
    from lughus.engine.tools import ToolRegistry
    from lughus.testing import MockStreamingLLM

    llm = MockStreamingLLM(["Hello world!"])
    registry = ToolRegistry()
    runner = GovernedAgentRunner()

    events: list[RunEvent] = []
    async for evt in runner.stream(llm, system=".", context="Hi", registry=registry, tool_names=[]):
        events.append(evt)

    assert len(events) == 4  # started, delta ("Hello "), delta ("world!"), completed
    assert events[0].type == "run.started"
    assert events[1].type == "text.delta"
    assert events[3].type == "run.completed"
    assert events[3].data["text"] == "Hello world!"


@pytest.mark.asyncio
async def test_agent_runner_stream_failure():
    from lughus.agent.runner import GovernedAgentRunner
    from lughus.engine.tools import ToolRegistry

    class BrokenStreamingLLM:
        model = "broken"

        async def astream(self, **_):
            raise RuntimeError("Stream error")

    runner = GovernedAgentRunner()
    registry = ToolRegistry()
    events: list[RunEvent] = []

    with pytest.raises(RuntimeError, match="Stream error"):
        async for evt in runner.stream(
            BrokenStreamingLLM(), system=".", context="Hi", registry=registry, tool_names=[]
        ):
            events.append(evt)

    assert len(events) == 2
    assert events[0].type == "run.started"
    assert events[1].type == "run.failed"
    assert events[1].data["error_code"] == "RuntimeError"
