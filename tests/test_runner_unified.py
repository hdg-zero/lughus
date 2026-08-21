"""Tests for the unified GovernedAgentRunner with optional governance.

Verifies that a single runner class handles both ungoverned (legacy AgentRunner)
and governed execution paths, and that the backward-compatible alias works.
"""

from __future__ import annotations

from typing import Any

import pytest

from lughus.application import AgentRuntime
from lughus.governance.approval import InMemoryApprovalStore
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.context import ContextManager
from lughus.domain import RunEvent
from lughus.event_stream import InMemoryEventSink
from lughus.governance.idempotency import InMemoryIdempotencyStore
from lughus.persistence import InMemoryRunStore
from lughus.governance.policy import AllowAllPolicy, Principal
from lughus.runner import AgentRunner, GovernedAgentRunner
from lughus.infra.runtime import ExecutionRuntime
from lughus.testing import MockLLM
from lughus.tools import ToolRegistry

# ── Identity: AgentRunner is GovernedAgentRunner ─────────────────────


def test_agent_runner_is_governed_agent_runner():
    """The backward-compat alias points to the same class."""
    assert AgentRunner is GovernedAgentRunner


def test_top_level_imports_resolve_to_same_class():
    """Both names are importable from the top-level package."""
    import lughus

    assert lughus.AgentRunner is lughus.GovernedAgentRunner


# ── Ungoverned path (no runtime) ────────────────────────────────────


@pytest.mark.asyncio
async def test_ungoverned_run_produces_expected_events():
    """Without a runtime the runner emits run.started and run.completed."""
    llm = MockLLM(["Hello unified"])
    registry = ToolRegistry()
    runner = GovernedAgentRunner()  # no runtime

    result = await runner.run(llm, system=".", context="Hi", registry=registry, tool_names=[])
    assert str(result) == "Hello unified"

    events = runner.events.snapshot()
    assert len(events) == 2
    types = [e.type for e in events]
    assert types == ["run.started", "run.completed"]
    assert events[1].data["text"] == "Hello unified"


@pytest.mark.asyncio
async def test_ungoverned_run_failure_produces_failed_event():
    """Without a runtime, an LLM error emits run.failed."""

    class BrokenLLM:
        model = "broken"

        async def generate(self, **_: Any) -> None:
            raise RuntimeError("boom")

    runner = GovernedAgentRunner()
    registry = ToolRegistry()
    with pytest.raises(RuntimeError, match="boom"):
        await runner.run(BrokenLLM(), system=".", context="Hi", registry=registry, tool_names=[])

    events = runner.events.snapshot()
    assert len(events) == 2
    assert events[0].type == "run.started"
    assert events[1].type == "run.failed"
    assert events[1].data["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_ungoverned_run_with_explicit_event_sink():
    """An explicit event_sink is honoured in ungoverned mode."""
    sink = InMemoryEventSink()
    llm = MockLLM(["ok"])
    runner = GovernedAgentRunner(event_sink=sink)

    await runner.run(llm, system=".", context="Hi", registry=ToolRegistry(), tool_names=[])

    assert runner.events is sink
    assert len(sink.snapshot()) == 2


@pytest.mark.asyncio
async def test_ungoverned_stream_produces_expected_events():
    """stream() works without governance."""
    from lughus.testing import MockStreamingLLM

    llm = MockStreamingLLM(["Hello world!"])
    runner = GovernedAgentRunner()
    events: list[RunEvent] = []
    async for evt in runner.stream(
        llm, system=".", context="Hi", registry=ToolRegistry(), tool_names=[]
    ):
        events.append(evt)

    assert events[0].type == "run.started"
    assert events[-1].type == "run.completed"
    assert events[-1].data["text"] == "Hello world!"


# ── Governed path (with runtime) ────────────────────────────────────


def _build_runtime() -> AgentRuntime:
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
async def test_governed_run_persists_tool_events():
    """With a runtime the governed path persists tool events."""
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
    async def greet(*, state: dict, name: str) -> str:
        return f"Hello, {name}!"

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM(
        [
            [{"name": "greet", "arguments": {"name": "World"}, "id": "c1"}],
            "Done!",
        ]
    )

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
async def test_governed_run_creates_checkpoint():
    """The governed path saves a checkpoint after tool execution."""
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
    async def echo(*, state: dict, msg: str) -> str:
        return msg

    runner = GovernedAgentRunner(runtime)
    principal = Principal(subject="user-1", tenant_id="t-1")
    llm = MockLLM(
        [
            [{"name": "echo", "arguments": {"msg": "hi"}, "id": "c1"}],
            "echoed",
        ]
    )

    await runner.run(
        llm,
        objective="echo test",
        principal=principal,
        registry=registry,
        system="Test",
    )

    store: InMemoryRunStore = runtime.run_store  # type: ignore[assignment]
    for run_id in store._runs:
        checkpoint = await runtime.checkpoint_store.latest(run_id)
        assert checkpoint is not None
        assert checkpoint.run_id == run_id

    await runtime.execution.close()


@pytest.mark.asyncio
async def test_same_class_handles_both_modes():
    """One class instance for ungoverned, another for governed -- same type."""
    simple_runner = GovernedAgentRunner()
    governed_runner = GovernedAgentRunner(_build_runtime())

    assert type(simple_runner) is type(governed_runner)
    assert simple_runner.runtime is None
    assert governed_runner.runtime is not None

    # Simple path
    llm_simple = MockLLM(["simple result"])
    result_simple = await simple_runner.run(
        llm_simple, system=".", context="test", registry=ToolRegistry(), tool_names=[]
    )
    assert str(result_simple) == "simple result"
    simple_events = simple_runner.events.snapshot()
    assert [e.type for e in simple_events] == ["run.started", "run.completed"]

    # Governed path
    runtime = governed_runner.runtime
    registry = ToolRegistry()

    @registry.tool(
        "noop",
        "No-op tool",
        {"type": "object", "properties": {}},
    )
    async def noop(*, state: dict) -> str:
        return "done"

    llm_gov = MockLLM(
        [
            [{"name": "noop", "arguments": {}, "id": "c1"}],
            "governed result",
        ]
    )
    result_gov = await governed_runner.run(
        llm_gov,
        objective="noop test",
        principal=Principal(subject="u", tenant_id="t"),
        registry=registry,
        system="Test",
    )
    assert "governed result" in str(result_gov)

    await runtime.execution.close()
