"""Public API parity checks. Run with the project's dev dependencies."""

import contextlib

import pytest

from lughus.agent.runner import GovernedAgentRunner
from lughus.core.errors import RunSuspended
from lughus.engine.tools import ToolRegistry
from lughus.governance.policy import DecisionKind, PolicyDecision, Principal
from lughus.testing import MockLLM, MockStreamingLLM
from tests.test_runner_unified import _build_runtime


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_policy_denial_identical(streaming: bool) -> None:
    class Deny:
        async def evaluate(self, proposal, principal):
            return PolicyDecision(DecisionKind.DENY, "test_deny")

    from dataclasses import replace

    runtime = replace(_build_runtime(), policy=Deny())
    registry = ToolRegistry()
    calls = []

    @registry.tool
    def act() -> str:
        calls.append(1)
        return "acted"

    replies = [[{"name": "act", "arguments": {}, "id": "t1"}], "denied"]
    llm = (MockStreamingLLM if streaming else MockLLM)(replies)
    runner = GovernedAgentRunner(runtime)
    kwargs = dict(objective="act", principal=Principal("u", "t"), registry=registry)
    try:
        if streaming:
            async with contextlib.aclosing(runner.stream(llm, **kwargs)) as events:
                result = [e async for e in events]
            assert result[-1].type == "run.completed"
        else:
            assert str(await runner.run(llm, **kwargs)) == "denied"
        assert calls == []
        assert not await runtime.budget.outstanding()
    finally:
        await runtime.execution.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_approval_suspends_both_paths(streaming: bool) -> None:
    runtime = _build_runtime()
    registry = ToolRegistry()

    @registry.tool(requires_approval=True)
    def act() -> str:
        raise AssertionError("Unapproved tool must not execute")

    replies = [[{"name": "act", "arguments": {}, "id": "t1"}]]
    llm = (MockStreamingLLM if streaming else MockLLM)(replies)
    runner = GovernedAgentRunner(runtime)
    kwargs = dict(objective="act", principal=Principal("u", "t"), registry=registry)
    try:
        with pytest.raises(RunSuspended):
            if streaming:
                async with contextlib.aclosing(runner.stream(llm, **kwargs)) as events:
                    _ = [e async for e in events]
            else:
                await runner.run(llm, **kwargs)
    finally:
        await runtime.execution.close()
