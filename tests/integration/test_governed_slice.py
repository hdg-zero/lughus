"""End-to-end test of the governed vertical slice.

Verifies that a governed run persists tool events with globally unique
sequences, creates checkpoints, and maintains sequence integrity.
"""

from __future__ import annotations

from typing import Any

import pytest

from lughus.application import AgentRuntime, GovernedAgentRunner
from lughus.approval import InMemoryApprovalStore
from lughus.budget import BudgetLedger, BudgetLimit
from lughus.context import ContextManager
from lughus.event_stream import InMemoryEventSink
from lughus.idempotency import InMemoryIdempotencyStore
from lughus.persistence import InMemoryRunStore
from lughus.policy import AllowAllPolicy, Principal
from lughus.runtime import ExecutionRuntime
from lughus.testing import MockLLM
from lughus.tools import ToolRegistry


def _build_runtime() -> AgentRuntime:
    """Build a minimal AgentRuntime with all governance components."""
    store = InMemoryRunStore()
    return AgentRuntime(
        execution=ExecutionRuntime(),
        policy=AllowAllPolicy(),
        approvals=InMemoryApprovalStore(),
        idempotency=InMemoryIdempotencyStore(),
        run_store=store,
        event_store=store,
        checkpoint_store=store,
        events=InMemoryEventSink(),
        budget=BudgetLedger(BudgetLimit(tool_calls=100)),
        context=ContextManager(max_characters=100_000),
    )


@pytest.mark.asyncio
async def test_governed_run_persists_tool_events() -> None:
    """Tool calls and results appear in the event store."""
    runtime = _build_runtime()
    registry = ToolRegistry()

    @registry.tool(
        "greet",
        "Greet someone",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    async def greet(*, state: Any, name: str) -> str:
        return f"Hello, {name}!"

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM([
        [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
        "Done!",
    ])

    result = await runner.run(
        llm,
        objective="greet the world",
        principal=principal,
        registry=registry,
        system="You are a test assistant.",
    )

    assert "Done" in str(result)

    store: InMemoryRunStore = runtime.run_store  # type: ignore[assignment]
    for run_id in store._runs:
        events = await store.read(run_id)
        event_types = [e.type for e in events]
        assert "run.created" in event_types
        assert "run.started" in event_types
        assert "tool_start" in event_types
        assert "tool_result" in event_types
        assert "run.completed" in event_types

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_sequences_strictly_increasing_no_gaps() -> None:
    """All events for a run have strictly increasing sequences with no gaps."""
    runtime = _build_runtime()
    registry = ToolRegistry()

    @registry.tool(
        "add",
        "Add numbers",
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    )
    async def add(*, state: Any, a: int, b: int) -> str:
        return str(a + b)

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM([
        [{"name": "add", "arguments": {"a": 1, "b": 2}, "id": "c1"}],
        "Result is 3",
    ])

    await runner.run(
        llm,
        objective="add numbers",
        principal=principal,
        registry=registry,
        system="Test",
    )

    store: InMemoryRunStore = runtime.run_store  # type: ignore[assignment]
    for run_id in store._runs:
        events = await store.read(run_id)
        sequences = [e.sequence for e in events]
        # Strictly increasing
        for i in range(1, len(sequences)):
            assert sequences[i] > sequences[i - 1], f"Sequences not increasing: {sequences}"
        # No gaps
        assert sequences == list(range(sequences[0], sequences[0] + len(sequences))), (
            f"Gap in sequences: {sequences}"
        )

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_checkpoint_saved_after_run() -> None:
    """A checkpoint is persisted for the run."""
    runtime = _build_runtime()
    registry = ToolRegistry()

    @registry.tool(
        "echo",
        "Echo input",
        {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )
    async def echo(*, state: Any, msg: str) -> str:
        return msg

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM([
        [{"name": "echo", "arguments": {"msg": "hi"}, "id": "c1"}],
        "echoed",
    ])

    await runner.run(
        llm,
        objective="echo test",
        principal=principal,
        registry=registry,
        system="Test",
    )

    checkpoint_store = runtime.checkpoint_store
    store: InMemoryRunStore = runtime.run_store  # type: ignore[assignment]
    for run_id in store._runs:
        checkpoint = await checkpoint_store.latest(run_id)
        assert checkpoint is not None, "No checkpoint saved"
        assert checkpoint.run_id == run_id

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_tool_result_persisted_for_each_tool_call() -> None:
    """Every tool_start event has a corresponding tool_result event."""
    runtime = _build_runtime()
    registry = ToolRegistry()

    @registry.tool(
        "double",
        "Double a number",
        {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
            "required": ["n"],
        },
    )
    async def double(*, state: Any, n: int) -> str:
        return str(n * 2)

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM([
        [{"name": "double", "arguments": {"n": 5}, "id": "c1"}],
        [{"name": "double", "arguments": {"n": 10}, "id": "c2"}],
        "All doubled",
    ])

    await runner.run(
        llm,
        objective="double numbers",
        principal=principal,
        registry=registry,
        system="Test",
    )

    store: InMemoryRunStore = runtime.run_store  # type: ignore[assignment]
    for run_id in store._runs:
        events = await store.read(run_id)
        tool_starts = [e for e in events if e.type == "tool_start"]
        tool_results = [e for e in events if e.type == "tool_result"]
        assert len(tool_results) >= len(tool_starts), (
            f"Missing results: {len(tool_starts)} starts, {len(tool_results)} results"
        )

    await runtime.execution.close()
