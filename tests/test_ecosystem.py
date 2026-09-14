import pytest

from lughus.core.domain import RunEvent
from lughus.engine.delegation import (
    DelegationCycleError,
    DelegationRequest,
    DelegationResult,
    Delegator,
)
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.interfaces.mcp import MCPAdapter, MCPServerConfig, MCPToolDescriptor
from lughus.testing.evaluation import Scenario, evaluate_scenario


@pytest.mark.asyncio
async def test_scenario_evaluation_is_deterministic():
    scenario = Scenario("happy", "objective", required_event_types=frozenset({"run.started"}))

    async def execute(_):
        return [RunEvent("run.started", "run", 0), RunEvent("run.completed", "run", 1)]

    result = await evaluate_scenario(scenario, execute)
    assert result.passed


@pytest.mark.asyncio
async def test_scenario_evaluation_failure_branches():
    # 1. max_events exceeded
    scenario = Scenario(
        "exceeded",
        "obj",
        max_events=1,
        required_event_types=frozenset({"run.started"}),
        forbidden_event_types=frozenset({"run.error"}),
        expected_terminal_event="run.completed",
    )

    async def _exec_exceeded(_):
        return [RunEvent("run.started", "run", 0), RunEvent("run.completed", "run", 1)]

    result = await evaluate_scenario(scenario, _exec_exceeded)
    assert not result.passed
    assert any("event count" in f for f in result.failures)

    # 2. missing required event and forbidden event present
    scenario_missing_forbidden = Scenario(
        "missing_forbidden",
        "obj",
        required_event_types=frozenset({"run.started", "run.required"}),
        forbidden_event_types=frozenset({"run.forbidden"}),
        expected_terminal_event="run.completed",
    )

    async def _exec_missing_forbidden(_):
        return [
            RunEvent("run.started", "run", 0),
            RunEvent("run.forbidden", "run", 1),
            RunEvent("run.completed", "run", 2),
        ]

    result2 = await evaluate_scenario(scenario_missing_forbidden, _exec_missing_forbidden)
    assert not result2.passed
    assert any("missing events: run.required" in f for f in result2.failures)
    assert any("forbidden events: run.forbidden" in f for f in result2.failures)

    # 3. empty events (terminal event missing)
    async def _exec_empty(_):
        return []

    result_empty = await evaluate_scenario(
        Scenario("empty", "obj", expected_terminal_event="run.completed"),
        _exec_empty,
    )
    assert not result_empty.passed
    assert any("terminal event must be run.completed" in f for f in result_empty.failures)

    # 4. non-monotonic / non-unique sequences
    async def _exec_seq(_):
        return [RunEvent("run.started", "run", 1), RunEvent("run.completed", "run", 0)]

    result_seq = await evaluate_scenario(
        Scenario("bad_seq", "obj", expected_terminal_event="run.completed"),
        _exec_seq,
    )
    assert not result_seq.passed
    assert any("event sequences are not unique and monotonic" in f for f in result_seq.failures)


class _MCP:
    origin = "https://mcp.example"

    async def list_tools(self):
        return [
            MCPToolDescriptor("allowed", "safe", {"type": "object"}),
            MCPToolDescriptor("hidden", "hidden", {"type": "object"}),
        ]

    async def call_tool(self, name, arguments):
        return {"name": name, "arguments": arguments}


@pytest.mark.asyncio
async def test_mcp_allowlist_applies_to_discovery_and_invocation():
    adapter = MCPAdapter(_MCP(), MCPServerConfig("https://mcp.example", frozenset({"allowed"})))
    assert [tool.name for tool in await adapter.refresh()] == ["allowed"]
    assert (await adapter._invoke("allowed", {}))["name"] == "allowed"
    with pytest.raises(PermissionError):
        await adapter._invoke("hidden", {})


class _Remote:
    async def delegate(self, request):
        return DelegationResult("task", "completed")


@pytest.mark.asyncio
async def test_delegation_consumes_depth_budget_and_rejects_cycles():
    ledger = BudgetLedger(BudgetLimit())
    result = await Delegator(_Remote(), ledger).delegate(
        DelegationRequest("run", "agent-b", "research", "objective", ("agent-a",))
    )
    assert result.status == "completed"
    assert (await ledger.snapshot())["delegation_depth"] == 1
    with pytest.raises(DelegationCycleError):
        DelegationRequest("run", "agent-a", "research", "objective", ("agent-a",))
