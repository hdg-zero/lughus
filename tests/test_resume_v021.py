"""Public API durable resume with a freshly created runtime, not pre-approval."""

import contextlib

import pytest

from lughus.agent.application import AgentRuntime
from lughus.agent.runner import GovernedAgentRunner
from lughus.core.context import ContextManager
from lughus.core.errors import RunSuspended
from lughus.core.event_stream import InMemoryEventSink
from lughus.engine.tools import ToolRegistry
from lughus.governance.approval import ApprovalStatus
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.governance.idempotency import InMemoryIdempotencyStore
from lughus.governance.policy import AllowAllPolicy, Principal
from lughus.infra.runtime import ExecutionRuntime
from lughus.persistence.sqlite import SQLiteApprovalStore, SQLiteStore
from lughus.testing import MockLLM, MockStreamingLLM


def runtime(path):
    store = SQLiteStore(path)
    return AgentRuntime(
        execution=ExecutionRuntime(),
        policy=AllowAllPolicy(),
        approvals=SQLiteApprovalStore(store),
        idempotency=InMemoryIdempotencyStore(),
        run_store=store,
        event_store=store,
        checkpoint_store=store,
        events=InMemoryEventSink(),
        budget=BudgetLedger(BudgetLimit()),
        context=ContextManager(10000),
        journal=store,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_suspend_then_resume_with_new_runtime(tmp_path, streaming: bool) -> None:
    rt = runtime(tmp_path / "runs.db")
    registry = ToolRegistry()
    calls = []

    @registry.tool(requires_approval=True)
    async def act() -> str:
        calls.append(1)
        return "acted"

    principal = Principal("user", "tenant")
    llm = (MockStreamingLLM if streaming else MockLLM)(
        [[{"name": "act", "arguments": {}, "id": "c1"}]]
    )
    runner = GovernedAgentRunner(rt)
    with pytest.raises(RunSuspended) as caught:
        if streaming:
            async with contextlib.aclosing(
                runner.stream(llm, objective="act", principal=principal, registry=registry)
            ) as events:
                _ = [event async for event in events]
        else:
            await runner.run(llm, objective="act", principal=principal, registry=registry)
    suspended = caught.value
    assert not calls
    await rt.approvals.decide(
        suspended.pending_requests[0].request_id, ApprovalStatus.APPROVED, "reviewer"
    )
    await rt.execution.close()

    rt = runtime(tmp_path / "runs.db")
    runner = GovernedAgentRunner(rt)
    if streaming:
        async with contextlib.aclosing(
            runner.resume_stream(
                suspended.run_id, MockStreamingLLM(["done"]), principal=principal, registry=registry
            )
        ) as events:
            result = [event async for event in events]
        assert result[-1].data["text"] == "done"
    else:
        assert (
            str(
                await runner.resume(
                    suspended.run_id, MockLLM(["done"]), principal=principal, registry=registry
                )
            )
            == "done"
        )
    assert calls == [1]
    await rt.execution.close()
