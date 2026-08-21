"""Runtime ownership, lifecycle and honoured limits.

Key properties:

* The implicit ExecutionRuntime is owned and closed by the loop;
* ToolExecutionConfig is inert and does not allocate resources;
* Capacities belong to ExecutionRuntime, not per-loop guardrails.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from lughus import ExecutionRuntime, ToolExecutionConfig, ToolRegistry, agent_loop
from lughus.core.errors import LoopLimitError
from lughus.loop._execute import _execute_tools
from lughus.infra.runtime import RuntimeConfig
from lughus.testing import MockLLM


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.tool(
        "noop",
        "Do nothing",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    def noop(*, state) -> str:
        return "ok"

    return reg


# ── R5: configuration is inert ────────────────────────────────────────────────


def test_constructing_a_config_allocates_no_thread() -> None:
    """A configuration is a value. Constructing one must not spawn a thread pool."""
    before = threading.active_count()
    configs = [ToolExecutionConfig() for _ in range(50)]
    assert all(cfg.runtime is None for cfg in configs)
    assert threading.active_count() == before


# ── Ownership ─────────────────────────────────────────────────────────────────


async def test_implicit_runtime_is_closed_on_success(registry: ToolRegistry) -> None:
    created: list[ExecutionRuntime] = []
    original = ExecutionRuntime.__init__

    def spy(self, config=None):  # type: ignore[no-untyped-def]
        original(self, config)
        created.append(self)

    ExecutionRuntime.__init__ = spy  # type: ignore[method-assign]
    try:
        await agent_loop(
            MockLLM(["done"]),
            system="s",
            context="c",
            registry=registry,
            tool_names=[],
        )
    finally:
        ExecutionRuntime.__init__ = original  # type: ignore[method-assign]

    assert len(created) == 1, "the loop should create exactly one runtime"
    assert created[0]._closed is True, "the runtime it created must be closed"


async def test_implicit_runtime_is_closed_when_the_loop_raises(
    registry: ToolRegistry,
) -> None:
    created: list[ExecutionRuntime] = []
    original = ExecutionRuntime.__init__

    def spy(self, config=None):  # type: ignore[no-untyped-def]
        original(self, config)
        created.append(self)

    ExecutionRuntime.__init__ = spy  # type: ignore[method-assign]
    try:
        with pytest.raises(LoopLimitError):
            await agent_loop(
                MockLLM([[{"name": "noop", "arguments": {}, "id": "c1"}]] * 3),
                system="s",
                context="c",
                registry=registry,
                tool_names=["noop"],
                max_iterations=1,
            )
    finally:
        ExecutionRuntime.__init__ = original  # type: ignore[method-assign]

    assert created and created[0]._closed is True


async def test_injected_runtime_is_not_closed_by_the_loop(registry: ToolRegistry) -> None:
    """An injected runtime stays the caller's property."""
    runtime = ExecutionRuntime()
    try:
        await agent_loop(
            MockLLM(["done"]),
            system="s",
            context="c",
            registry=registry,
            tool_names=[],
            tool_config=ToolExecutionConfig(runtime=runtime),
        )
        assert runtime._closed is False
    finally:
        await runtime.close()


async def test_repeated_loops_do_not_leak_threads(registry: ToolRegistry) -> None:
    """Regression test: repeated loops must not leak threads. Fails on 0.10.1."""
    before = threading.active_count()
    for _ in range(40):
        await agent_loop(
            MockLLM(["done"]),
            system="s",
            context="c",
            registry=registry,
            tool_names=[],
        )
    await asyncio.sleep(0.05)  # let the pools' worker threads finish exiting
    assert threading.active_count() <= before + 2, (
        f"thread count grew from {before} to {threading.active_count()}"
    )


async def test_execute_tools_refuses_a_config_without_runtime(
    registry: ToolRegistry,
) -> None:
    """_execute_tools must never manufacture a runtime it would then leak."""
    with pytest.raises(RuntimeError, match="requires a ToolExecutionConfig"):
        await _execute_tools(
            [("c1", "noop", "{}")],
            registry,
            {},
            config=None,
        )


# ── declared limits must take effect ────────────────────────────


async def test_implicit_runtime_uses_module_defaults(registry: ToolRegistry) -> None:
    """The implicit runtime uses the module-level constants."""
    from lughus.loop._config import DEFAULT_MAX_GLOBAL_TOOLS, DEFAULT_MAX_SYNC_THREAD_WORKERS

    seen: list[RuntimeConfig] = []
    original = ExecutionRuntime.__init__

    def spy(self, config=None):  # type: ignore[no-untyped-def]
        original(self, config)
        seen.append(self.config)

    ExecutionRuntime.__init__ = spy  # type: ignore[method-assign]
    try:
        await agent_loop(
            MockLLM(["done"]),
            system="s",
            context="c",
            registry=registry,
            tool_names=[],
            tool_config=ToolExecutionConfig(tool_queue_timeout=7.0),
        )
    finally:
        ExecutionRuntime.__init__ = original  # type: ignore[method-assign]

    assert seen, "no runtime was created"
    assert seen[0].max_sync_workers == DEFAULT_MAX_SYNC_THREAD_WORKERS
    assert seen[0].max_global_tools == DEFAULT_MAX_GLOBAL_TOOLS
    assert seen[0].queue_timeout == 7.0


async def test_injected_runtime_imposes_its_capacities() -> None:
    """An injected runtime is accepted without conflict checks."""
    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=8, max_sync_workers=4))
    try:
        cfg = ToolExecutionConfig(runtime=runtime)
        assert cfg.runtime is runtime
    finally:
        await runtime.close()


# ── lifecycle and resource locks ─────────────────────────


async def test_resource_locks_do_not_accumulate() -> None:
    """Regression test: resource locks must not accumulate without bound.

    Resource keys are derived from tool arguments, so an unbounded dict is fed by
    potentially model-controlled data.
    """
    runtime = ExecutionRuntime()
    try:
        for i in range(500):
            async with runtime.resource_slot(f"key-{i}"):
                pass
        assert len(runtime._resource_locks) == 0
    finally:
        await runtime.close()


async def test_resource_slot_still_serialises_the_same_key() -> None:
    runtime = ExecutionRuntime()
    order: list[tuple[str, int]] = []

    async def worker(n: int) -> None:
        async with runtime.resource_slot("shared"):
            order.append(("in", n))
            await asyncio.sleep(0.01)
            order.append(("out", n))

    try:
        await asyncio.gather(*(worker(i) for i in range(3)))
        # Every "in" must be immediately followed by its matching "out".
        assert all(order[i][0] == "in" and order[i + 1][0] == "out" for i in range(0, 6, 2))
        assert "shared" not in runtime._resource_locks
    finally:
        await runtime.close()


async def test_resource_slot_releases_on_exception() -> None:
    runtime = ExecutionRuntime()
    try:
        with pytest.raises(ValueError):
            async with runtime.resource_slot("boom"):
                raise ValueError("boom")
        assert "boom" not in runtime._resource_locks
    finally:
        await runtime.close()


async def test_close_wait_true_waits_for_running_sync_tools() -> None:
    """Fails on 0.10.1: `wait` was ignored and shutdown(wait=False) always ran."""
    import time as _time

    runtime = ExecutionRuntime(RuntimeConfig(max_sync_workers=2))
    finished: list[bool] = []

    def slow() -> None:
        _time.sleep(0.2)
        finished.append(True)

    task = asyncio.ensure_future(runtime.run_sync(slow))
    await asyncio.sleep(0.02)
    await runtime.close(wait=True)
    assert finished == [True], "close(wait=True) must not return mid-execution"
    await task


async def test_close_is_idempotent() -> None:
    runtime = ExecutionRuntime()
    await runtime.close()
    await runtime.close(wait=False)
    assert runtime._closed is True
