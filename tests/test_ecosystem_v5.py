import json

import pytest

from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.engine.delegation import (
    DelegationCycleError,
    DelegationRequest,
    DelegationResult,
    Delegator,
)
from lughus.core.domain import RunEvent
from lughus.testing.evaluation import Scenario, evaluate_scenario
from lughus.interfaces.mcp import MCPAdapter, MCPServerConfig, MCPToolDescriptor
from lughus.persistence.replay import ReplayBundle


def test_replay_bundle_round_trip_and_tamper_detection():
    bundle = ReplayBundle(
        "0.5.0", "run", {"model": "test"}, (RunEvent("run.completed", "run", 0),)
    ).seal()
    restored = ReplayBundle.from_json(bundle.to_json())
    assert restored.verify()
    tampered = json.loads(bundle.to_json())
    tampered["configuration"]["model"] = "other"
    with pytest.raises(ValueError, match="integrity"):
        ReplayBundle.from_json(json.dumps(tampered))


@pytest.mark.asyncio
async def test_scenario_evaluation_is_deterministic():
    scenario = Scenario("happy", "objective", required_event_types=frozenset({"run.started"}))

    async def execute(_):
        return [RunEvent("run.started", "run", 0), RunEvent("run.completed", "run", 1)]

    result = await evaluate_scenario(scenario, execute)
    assert result.passed


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
