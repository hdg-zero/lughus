"""Tests for _execute_tools() — parallel tool execution in the agent loop."""

from __future__ import annotations

import asyncio
import functools
import json
import threading
import time

import pytest

from lughus import ToolRegistry
from lughus.loop import ToolExecutionConfig, _execute_tools, collect_tool_events


@pytest.fixture
def registry_with_tools() -> tuple[ToolRegistry, list]:
    """Registry pre-loaded with sync, async, and slow tools."""
    registry = ToolRegistry()
    call_log: list[str] = []

    @registry.tool(
        "sync_tool",
        "Sync tool.",
        {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )
    def sync_tool(*, x: str, state) -> str:
        call_log.append(f"sync:{x}")
        return json.dumps({"result": x.upper()})

    @registry.tool(
        "async_tool",
        "Async tool.",
        {
            "type": "object",
            "properties": {"y": {"type": "integer"}},
            "required": ["y"],
        },
    )
    async def async_tool(*, y: int, state) -> str:
        call_log.append(f"async:{y}")
        return json.dumps({"result": y * 2})

    @registry.tool(
        "slow_tool",
        "Slow tool for parallelism test.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    async def slow_tool(*, state) -> str:
        await asyncio.sleep(0.05)
        call_log.append("slow:done")
        return json.dumps({"slow": True})

    @registry.tool(
        "failing_tool",
        "Tool that always fails.",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
    )
    def failing_tool(*, state) -> str:
        raise ValueError("intentional failure")

    return registry, call_log


@pytest.mark.asyncio
async def test_sync_tool_executes(registry_with_tools) -> None:
    """A sync tool returns the correct result."""
    registry, _ = registry_with_tools
    results = await _execute_tools(
        [("call_1", "sync_tool", '{"x": "hello"}')],
        registry,
        state=None,
    )
    assert len(results) == 1
    tc_id, output = results[0]
    assert tc_id == "call_1"
    assert json.loads(output) == {"result": "HELLO"}


@pytest.mark.asyncio
async def test_tool_events_are_collected(registry_with_tools) -> None:
    """Tool execution emits UI-observable start and result events."""
    registry, _ = registry_with_tools
    events: list[dict] = []

    with collect_tool_events(events.append):
        await _execute_tools(
            [("call_1", "sync_tool", '{"x": "hello"}')],
            registry,
            state=None,
        )

    assert events[0] == {
        "type": "tool_start",
        "tool_call_id": "call_1",
        "tool_name": "sync_tool",
        "arguments": '{"x": "hello"}',
    }
    assert events[1]["type"] == "tool_result"
    assert events[1]["tool_call_id"] == "call_1"
    assert events[1]["tool_name"] == "sync_tool"
    assert events[1]["status"] == "ok"
    assert json.loads(events[1]["output"]) == {"result": "HELLO"}
    assert events[1]["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_async_tool_executes(registry_with_tools) -> None:
    """An async tool returns the correct result."""
    registry, _ = registry_with_tools
    results = await _execute_tools(
        [("call_2", "async_tool", '{"y": 21}')],
        registry,
        state=None,
    )
    _, output = results[0]
    assert json.loads(output) == {"result": 42}


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_json(registry_with_tools) -> None:
    """An unknown tool name returns an error JSON without raising."""
    registry, _ = registry_with_tools
    results = await _execute_tools(
        [("call_3", "no_such_tool", "{}")],
        registry,
        state=None,
    )
    _, output = results[0]
    data = json.loads(output)
    assert "error" in data
    assert data["error_type"] == "ToolValidationError"
    assert "no_such_tool" in data["error"]


@pytest.mark.asyncio
async def test_failing_tool_returns_error_json(registry_with_tools) -> None:
    """A tool that raises an exception returns error JSON without propagating."""
    registry, _ = registry_with_tools
    results = await _execute_tools(
        [("call_4", "failing_tool", "{}")],
        registry,
        state=None,
    )
    _, output = results[0]
    data = json.loads(output)
    assert "error" in data
    assert data["error_type"] == "ToolExecutionError"
    assert "intentional failure" in data["error"]


@pytest.mark.asyncio
async def test_multiple_tools_run_in_parallel(registry_with_tools) -> None:
    """Multiple slow tools run concurrently, not sequentially."""
    registry, call_log = registry_with_tools
    n = 3
    tool_calls = [(f"call_{i}", "slow_tool", "{}") for i in range(n)]

    t0 = time.perf_counter()
    results = await _execute_tools(tool_calls, registry, state=None)
    elapsed = time.perf_counter() - t0

    assert len(results) == n
    # 3 tools × 50ms each, should run in ~50ms if truly parallel (not ~150ms)
    assert elapsed < 0.12, f"Expected parallel execution but took {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_empty_args_handled(registry_with_tools) -> None:
    """Empty raw_args string is treated as empty dict."""
    registry, _ = registry_with_tools
    results = await _execute_tools(
        [("call_5", "slow_tool", "")],
        registry,
        state=None,
    )
    _, output = results[0]
    assert json.loads(output) == {"slow": True}


@pytest.mark.asyncio
async def test_sync_blocking_tool_does_not_block_event_loop() -> None:
    """J1-2: A sync tool using time.sleep() does not block the event loop."""
    registry = ToolRegistry()

    @registry.tool("blocking", "Blocks for 50ms.", {"type": "object", "properties": {}})
    def blocking_tool(*, state) -> str:
        time.sleep(0.05)
        return json.dumps({"done": True})

    n = 3
    tool_calls = [(f"call_{i}", "blocking", "") for i in range(n)]

    t0 = time.perf_counter()
    results = await _execute_tools(tool_calls, registry, state=None)
    elapsed = time.perf_counter() - t0

    assert len(results) == n
    for _, output in results:
        assert json.loads(output) == {"done": True}
    # Must run in ~50ms (parallel), not ~150ms (sequential)
    assert elapsed < 0.12, (
        f"Expected parallel execution (~50ms) but took {elapsed:.3f}s — "
        "sync tool may still be blocking the event loop."
    )


@pytest.mark.asyncio
async def test_max_parallel_tools_limits_concurrency() -> None:
    """ToolExecutionConfig bounds per-iteration tool concurrency."""
    registry = ToolRegistry()
    running = 0
    max_seen = 0

    @registry.tool("slow", "Slow async tool.", {"type": "object", "properties": {}})
    async def slow(*, state) -> str:
        nonlocal running, max_seen
        running += 1
        max_seen = max(max_seen, running)
        await asyncio.sleep(0.03)
        running -= 1
        return json.dumps({"done": True})

    tool_calls = [(f"call_{i}", "slow", "{}") for i in range(4)]
    results = await _execute_tools(
        tool_calls,
        registry,
        state=None,
        config=ToolExecutionConfig(max_parallel_tools=2),
    )

    assert len(results) == 4
    assert max_seen == 2


@pytest.mark.asyncio
async def test_tool_timeout_returns_error_json() -> None:
    """A slow tool is stopped from blocking the loop forever."""
    registry = ToolRegistry()

    @registry.tool("too_slow", "Too slow.", {"type": "object", "properties": {}})
    async def too_slow(*, state) -> str:
        await asyncio.sleep(0.2)
        return json.dumps({"done": True})

    results = await _execute_tools(
        [("call_timeout", "too_slow", "{}")],
        registry,
        state=None,
        config=ToolExecutionConfig(tool_timeout=0.01),
    )

    data = json.loads(results[0][1])
    assert "error" in data
    assert data["error_type"] == "ToolTimeoutError"
    assert "timed out" in data["error"]


@pytest.mark.asyncio
async def test_tool_args_schema_validation() -> None:
    """LLM-provided tool args are validated before tool execution."""
    registry = ToolRegistry()
    called = False

    @registry.tool(
        "needs_int",
        "Needs an int.",
        {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )
    def needs_int(*, value: int, state) -> str:
        nonlocal called
        called = True
        return json.dumps({"value": value})

    results = await _execute_tools(
        [("call_bad_args", "needs_int", '{"value": "not-int"}')],
        registry,
        state=None,
    )

    data = json.loads(results[0][1])
    assert called is False
    assert data["error_type"] == "ToolValidationError"
    assert "Invalid arguments" in data["error"]


@pytest.mark.asyncio
async def test_tool_args_size_limit() -> None:
    """Oversized raw tool arguments are rejected before JSON parsing."""
    registry = ToolRegistry()

    @registry.tool("echo", "Echo.", {"type": "object", "properties": {}})
    def echo(*, state) -> str:
        return "{}"

    results = await _execute_tools(
        [("call_big_args", "echo", '{"x":"' + ("a" * 50) + '"}')],
        registry,
        state=None,
        config=ToolExecutionConfig(max_tool_args_chars=10),
    )

    data = json.loads(results[0][1])
    assert data["error_type"] == "ToolValidationError"
    assert "exceed" in data["error"]


@pytest.mark.asyncio
async def test_tool_output_size_limit() -> None:
    """Oversized tool output is replaced with a structured error."""
    registry = ToolRegistry()

    @registry.tool("big", "Big output.", {"type": "object", "properties": {}})
    def big(*, state) -> str:
        return "x" * 50

    results = await _execute_tools(
        [("call_big_output", "big", "{}")],
        registry,
        state=None,
        config=ToolExecutionConfig(max_tool_output_chars=10),
    )

    data = json.loads(results[0][1])
    assert data["error_type"] == "ToolValidationError"
    assert "Output from tool" in data["error"]


@pytest.mark.asyncio
async def test_max_global_tools_limits_process_concurrency() -> None:
    """ToolExecutionConfig bounds tool concurrency across simultaneous loop calls."""
    registry = ToolRegistry()
    running = 0
    max_seen = 0

    @registry.tool("slow", "Slow async tool.", {"type": "object", "properties": {}})
    async def slow(*, state) -> str:
        nonlocal running, max_seen
        running += 1
        max_seen = max(max_seen, running)
        await asyncio.sleep(0.03)
        running -= 1
        return json.dumps({"done": True})

    cfg = ToolExecutionConfig(max_parallel_tools=10, max_global_tools=1)

    await asyncio.gather(
        _execute_tools([("call_1", "slow", "{}")], registry, state=None, config=cfg),
        _execute_tools([("call_2", "slow", "{}")], registry, state=None, config=cfg),
    )

    assert max_seen == 1


@pytest.mark.asyncio
async def test_global_tool_queue_timeout_returns_error_json() -> None:
    """Waiting for a saturated global tool slot is bounded."""
    registry = ToolRegistry()
    started = asyncio.Event()
    release = asyncio.Event()

    @registry.tool("wait", "Wait.", {"type": "object", "properties": {}})
    async def wait(*, state) -> str:
        started.set()
        await release.wait()
        return json.dumps({"done": True})

    cfg = ToolExecutionConfig(
        max_parallel_tools=1,
        max_global_tools=1,
        tool_queue_timeout=0.01,
    )
    first = asyncio.create_task(
        _execute_tools([("call_1", "wait", "{}")], registry, state=None, config=cfg)
    )
    await started.wait()

    results = await _execute_tools(
        [("call_2", "wait", "{}")],
        registry,
        state=None,
        config=cfg,
    )

    release.set()
    await first
    data = json.loads(results[0][1])
    assert data["error_type"] == "ToolTimeoutError"
    assert "global tool slot" in data["error"]


@pytest.mark.asyncio
async def test_async_callable_tool_executes() -> None:
    """Callable objects with async __call__ are detected as async tools."""
    registry = ToolRegistry()

    class AsyncCallable:
        async def __call__(self, *, value: str, state) -> str:
            await asyncio.sleep(0)
            return json.dumps({"value": value})

    registry.tool(
        "callable",
        "Async callable.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )(AsyncCallable())

    results = await _execute_tools(
        [("call_callable", "callable", '{"value": "ok"}')],
        registry,
        state=None,
    )

    assert json.loads(results[0][1]) == {"value": "ok"}


@pytest.mark.asyncio
async def test_async_partial_tool_executes_without_sync_worker() -> None:
    """functools.partial around async tools is still detected as async."""
    registry = ToolRegistry()

    async def async_base(*, prefix: str, value: str, state) -> str:
        await asyncio.sleep(0)
        return json.dumps({"value": f"{prefix}{value}"})

    registry.tool(
        "partial_async",
        "Async partial.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    )(functools.partial(async_base, prefix="ok:"))

    results = await _execute_tools(
        [("call_partial", "partial_async", '{"value": "yes"}')],
        registry,
        state=None,
        config=ToolExecutionConfig(max_sync_thread_workers=1),
    )

    assert json.loads(results[0][1]) == {"value": "ok:yes"}


@pytest.mark.asyncio
async def test_sync_tool_worker_pool_is_bounded() -> None:
    """Synchronous tool execution uses a bounded worker pool."""
    registry = ToolRegistry()
    lock = threading.Lock()
    running = 0
    max_seen = 0

    @registry.tool("blocking", "Blocks briefly.", {"type": "object", "properties": {}})
    def blocking(*, state) -> str:
        nonlocal running, max_seen
        with lock:
            running += 1
            max_seen = max(max_seen, running)
        try:
            time.sleep(0.05)
            return json.dumps({"done": True})
        finally:
            with lock:
                running -= 1

    results = await _execute_tools(
        [(f"call_{index}", "blocking", "{}") for index in range(4)],
        registry,
        state=None,
        config=ToolExecutionConfig(
            max_parallel_tools=4,
            max_global_tools=4,
            max_sync_thread_workers=2,
        ),
    )

    assert len(results) == 4
    assert max_seen == 2


@pytest.mark.asyncio
async def test_global_tool_semaphore_is_shared_across_configurations() -> None:
    """The global tool semaphore is shared per event loop, even with different max_global_tools configs."""
    from lughus.loop._execute import _global_tool_semaphore

    sem1 = _global_tool_semaphore(2)
    sem2 = _global_tool_semaphore(3)

    assert sem1 is sem2
