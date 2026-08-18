"""Tests for ConcurrencyMode semantics."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from typing import Any

import pytest

from lughus import ConcurrencyMode, ToolRegistry
from lughus.errors import ToolValidationError
from lughus.loop import ToolExecutionConfig
from lughus.loop import _execute_tools as _raw_execute_tools
from lughus.runtime import ExecutionRuntime, RuntimeConfig


def _test_runtime() -> ExecutionRuntime:
    return ExecutionRuntime(RuntimeConfig(max_sync_workers=32))


async def _execute_tools(
    tool_calls: list[tuple[str, str, str]],
    registry: ToolRegistry,
    state: Any = None,
    config: ToolExecutionConfig | None = None,
) -> list[tuple[str, str]]:
    runtime_to_close: ExecutionRuntime | None = None
    if config is None:
        runtime_to_close = _test_runtime()
        config = ToolExecutionConfig(runtime=runtime_to_close)
    elif config.runtime is None:
        runtime_to_close = _test_runtime()
        config = dataclasses.replace(config, runtime=runtime_to_close)
    try:
        return await _raw_execute_tools(tool_calls, registry, state, config=config)
    finally:
        if runtime_to_close is not None:
            await runtime_to_close.close()


# ── PARALLEL_SAFE is the default ─────────────────────────────────────────────


def test_parallel_safe_is_default():
    """PARALLEL_SAFE should be the default concurrency mode on ToolDef."""
    registry = ToolRegistry()

    @registry.tool("noop", "No-op.", {"type": "object", "properties": {}})
    async def noop(*, state) -> str:
        return "ok"

    tool = registry.get_tool("noop")
    assert tool is not None
    assert tool.concurrency == ConcurrencyMode.PARALLEL_SAFE


# ── PARALLEL_SAFE: two parallel tools take max(t1, t2) not t1+t2 ─────────


@pytest.mark.asyncio
async def test_parallel_safe_runs_concurrently():
    """Two PARALLEL_SAFE tools should overlap, taking ~max(t1, t2) not t1+t2."""
    registry = ToolRegistry()
    delay = 0.1

    @registry.tool(
        "slow_a",
        "Slow A.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.PARALLEL_SAFE,
    )
    async def slow_a(*, state) -> str:
        await asyncio.sleep(delay)
        return json.dumps({"tool": "a"})

    @registry.tool(
        "slow_b",
        "Slow B.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.PARALLEL_SAFE,
    )
    async def slow_b(*, state) -> str:
        await asyncio.sleep(delay)
        return json.dumps({"tool": "b"})

    start = time.perf_counter()
    results = await _execute_tools(
        [("c1", "slow_a", "{}"), ("c2", "slow_b", "{}")],
        registry,
    )
    elapsed = time.perf_counter() - start

    assert len(results) == 2
    # Should be close to delay, not 2*delay — proving true parallelism.
    assert elapsed < delay * 1.8


# ── SERIAL_PER_TOOL: allows two different tools in parallel ───────────────


@pytest.mark.asyncio
async def test_serial_per_tool_allows_different_tools_in_parallel():
    """SERIAL_PER_TOOL serializes calls to the *same* tool but allows different tools to overlap."""
    registry = ToolRegistry()
    delay = 0.1

    @registry.tool(
        "tool_x",
        "Tool X.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.SERIAL_PER_TOOL,
    )
    async def tool_x(*, state) -> str:
        await asyncio.sleep(delay)
        return "x"

    @registry.tool(
        "tool_y",
        "Tool Y.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.SERIAL_PER_TOOL,
    )
    async def tool_y(*, state) -> str:
        await asyncio.sleep(delay)
        return "y"

    start = time.perf_counter()
    results = await _execute_tools(
        [("c1", "tool_x", "{}"), ("c2", "tool_y", "{}")],
        registry,
    )
    elapsed = time.perf_counter() - start

    assert len(results) == 2
    # Different tools run in parallel, so elapsed ~ delay, not 2*delay.
    assert elapsed < delay * 1.8


# ── GLOBAL_EXCLUSIVE: allows no other tool in parallel ────────────────────


@pytest.mark.asyncio
async def test_global_exclusive_serializes_everything():
    """GLOBAL_EXCLUSIVE must serialize all tool invocations sharing the lock."""
    registry = ToolRegistry()
    delay = 0.08

    @registry.tool(
        "excl_a",
        "Exclusive A.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.GLOBAL_EXCLUSIVE,
    )
    async def excl_a(*, state) -> str:
        await asyncio.sleep(delay)
        return "a"

    @registry.tool(
        "excl_b",
        "Exclusive B.",
        {"type": "object", "properties": {}},
        concurrency=ConcurrencyMode.GLOBAL_EXCLUSIVE,
    )
    async def excl_b(*, state) -> str:
        await asyncio.sleep(delay)
        return "b"

    start = time.perf_counter()
    results = await _execute_tools(
        [("c1", "excl_a", "{}"), ("c2", "excl_b", "{}")],
        registry,
    )
    elapsed = time.perf_counter() - start

    assert len(results) == 2
    # Both tools share the global lock, so they must run sequentially.
    assert elapsed >= delay * 1.8


# ── SERIAL_PER_RESOURCE without resource_key raises at registration ───────


def test_serial_per_resource_without_resource_key_raises():
    """SERIAL_PER_RESOURCE requires a resource_key; omitting it is a registration error."""
    registry = ToolRegistry()
    with pytest.raises(ToolValidationError, match="resource_key"):

        @registry.tool(
            "bad",
            "Missing resource key.",
            {"type": "object", "properties": {}},
            concurrency=ConcurrencyMode.SERIAL_PER_RESOURCE,
        )
        async def bad(*, state) -> str:
            return "never"


def test_serial_per_resource_with_resource_key_succeeds():
    """SERIAL_PER_RESOURCE with a resource_key should register without error."""
    registry = ToolRegistry()

    @registry.tool(
        "keyed",
        "Has resource key.",
        {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        concurrency=ConcurrencyMode.SERIAL_PER_RESOURCE,
        resource_key=lambda args: args["id"],
    )
    async def keyed(*, id: str, state) -> str:
        return id

    tool = registry.get_tool("keyed")
    assert tool is not None
    assert tool.concurrency == ConcurrencyMode.SERIAL_PER_RESOURCE
