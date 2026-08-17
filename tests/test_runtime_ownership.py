"""W1-02 / W1-03 / W1-05: runtime ownership, lifecycle and honoured limits.

Three defects converge here:

* N-03  the implicit ExecutionRuntime was never closed -> thread pool leak;
* F-05  a thread pool was allocated by *constructing a configuration object*;
* N-10  max_global_tools / max_sync_thread_workers on ToolExecutionConfig were
        silently ignored whenever the runtime was implicit.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from lughus import ExecutionRuntime, ToolExecutionConfig, ToolRegistry, agent_loop
from lughus.errors import LoopLimitError
from lughus.loop._execute import _execute_tools
from lughus.runtime import RuntimeConfig
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
    """The regression test for N-03. Fails on 0.10.1: one pool leaked per loop."""
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
            ["noop"],
            config=None,
        )
