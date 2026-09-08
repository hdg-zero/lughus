"""Requires real Pydantic/jsonschema and normal project dev dependencies."""

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from lughus.engine.tools import ToolRegistry
from lughus.governance.budget import BudgetLedger, BudgetLimit
from lughus.infra.runtime import ExecutionRuntime
from lughus.loop import ToolExecutionConfig, agent_loop
from lughus.loop._execute import _execute_tools
from lughus.testing import MockLLM


class WeatherQuery(BaseModel):
    city: str
    days: Annotated[int, Field(ge=1, le=7)]


@pytest.mark.asyncio
async def test_typed_input_is_hydrated() -> None:
    registry = ToolRegistry()
    seen = []

    @registry.tool
    async def weather(query: WeatherQuery) -> str:
        assert isinstance(query, WeatherQuery)
        seen.append(query.city)
        return query.city

    llm = MockLLM(
        [
            [{"name": "weather", "arguments": {"query": {"city": "Paris", "days": 2}}, "id": "c1"}],
            "done",
        ]
    )
    await agent_loop(llm, system="test", context="weather", registry=registry)
    assert seen == ["Paris"]


@pytest.mark.asyncio
async def test_annotated_constraints_reject_before_dispatch() -> None:
    registry = ToolRegistry()
    seen = []

    @registry.tool
    async def count(value: Annotated[int, Field(gt=0)]) -> str:
        seen.append(value)
        return str(value)

    llm = MockLLM([[{"name": "count", "arguments": {"value": -1}, "id": "c1"}], "rejected"])
    await agent_loop(llm, system="test", context="count", registry=registry)
    assert not seen


@pytest.mark.asyncio
async def test_failed_tool_settles_budget() -> None:
    registry = ToolRegistry()

    @registry.tool
    async def fail() -> str:
        raise ValueError("failure")

    ledger = BudgetLedger(BudgetLimit(tool_calls=1))
    async with ExecutionRuntime() as execution:
        cfg = ToolExecutionConfig(runtime=execution, budget=ledger)
        await _execute_tools([("c1", "fail", "{}")], registry, None, cfg)
    assert not await ledger.outstanding()
    assert (await ledger.snapshot())["tool_calls"] == 1
