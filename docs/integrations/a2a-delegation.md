# A2A Delegation Guide

Agent-to-Agent (A2A) delegation allows a primary Lughus run to orchestrate child agents across distributed environments.

## The Delegation Model
Delegation in Lughus (`lughus.engine.delegation`) revolves around safely requesting and tracking remote execution.
- `DelegationRequest`: Defines the target, required skill, objective, and crucially, the causal chain.
- `RemoteAgentClient`: A protocol your application implements to handle the actual wire transport (e.g., gRPC, HTTP).
- `Delegator`: The orchestrator that wraps requests, applying budget constraints before dispatch.

## Child Budgets
A parent agent cannot spawn infinite child agents. The `Delegator` hooks into a `BudgetLedger`. Before a request is dispatched, it reserves a `BudgetAmount` (e.g., `delegation_depth=1`). If the delegation completes, the budget is settled. If it fails, the reservation is released.

## Cycle Detection
To prevent recursive death-spirals, `DelegationRequest` mandates cycle detection:
- The `causal_chain` stores the history of agent IDs involved in the delegation path.
- If the `target_agent` is already in the chain, a `DelegationCycleError` is raised immediately.
- A configurable `max_depth` (default 4) acts as a hard ceiling on the delegation tree.

## Remote Artifacts
When a `DelegationResult` returns, any attached artifacts are treated strictly as untrusted data. They must be validated locally before being injected into the parent agent's context or event stream.

```python
import asyncio
from lughus.engine.delegation import DelegationRequest, Delegator


class MockBudgetLedger:
    async def reserve(self, amount):
        return "res_1"

    async def settle(self, reservation, amount):
        pass

    async def release(self, reservation):
        pass


class MockRemoteClient:
    async def delegate(self, request):
        from lughus.engine.delegation import DelegationResult

        return DelegationResult(remote_task_id="task_123", status="success")


async def execute_delegation():
    client = MockRemoteClient()
    budget = MockBudgetLedger()
    delegator = Delegator(client, budget)

    request = DelegationRequest(
        parent_run_id="run_001",
        target_agent="agent_researcher",
        skill="data_analysis",
        objective="Analyze quarterly metrics",
        causal_chain=("agent_orchestrator",),
        max_depth=3,
    )

    result = await delegator.delegate(request)
    print(f"Delegation completed with status: {result.status}")


if __name__ == "__main__":
    asyncio.run(execute_delegation())
```
