"""Tests for Pydantic-First DX tool configuration and execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from lughus import (
    ToolDef,
    ToolEffect,
    ToolRegistry,
    ToolRisk,
    agent_loop,
    tool,
)
from lughus.engine.schema import infer_tool_schema, parse_docstring
from lughus.testing import MockLLM


class WeatherQuery(BaseModel):
    city: str = Field(description="City name")
    days: int = Field(default=1, description="Number of forecast days")


class WeatherReport(BaseModel):
    city: str
    temperature: float
    unit: str


@dataclass
class SimpleState:
    counter: int = 0


def test_parse_docstring_google() -> None:
    doc = """Get the weather report for a city.

    Args:
        city: The target city name.
        unit: The temperature unit ('celsius' or 'fahrenheit').
    """
    desc, params = parse_docstring(doc)
    assert desc == "Get the weather report for a city."
    assert params["city"] == "The target city name."
    assert params["unit"] == "The temperature unit ('celsius' or 'fahrenheit')."


def test_parse_docstring_sphinx() -> None:
    doc = """Multiply two numbers together.

    :param a: The first integer operand.
    :param b: The second integer operand.
    :return: The product.
    """
    desc, params = parse_docstring(doc)
    assert desc == "Multiply two numbers together."
    assert params["a"] == "The first integer operand."
    assert params["b"] == "The second integer operand."


def test_schema_inference_primitives_and_defaults() -> None:
    def sample_func(
        name: str,
        count: int = 10,
        rate: float = 0.5,
        active: bool = True,
    ) -> str:
        """Sample function.

        Args:
            name: User name.
            count: Total count.
        """
        return f"{name}-{count}"

    _desc, doc_params = parse_docstring(sample_func.__doc__)
    schema, takes_state = infer_tool_schema(sample_func, doc_params=doc_params)

    assert takes_state is False
    assert schema["type"] == "object"
    assert "name" in schema["properties"]
    assert schema["properties"]["name"]["type"] == "string"
    assert schema["properties"]["name"]["description"] == "User name."
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["count"]["default"] == 10
    assert schema["required"] == ["name"]


def test_schema_inference_complex_types() -> None:
    def complex_func(
        tags: list[str],
        unit: Literal["celsius", "fahrenheit"] = "celsius",
    ) -> list[str]:
        return tags

    schema, takes_state = infer_tool_schema(complex_func)
    assert takes_state is False
    assert schema["properties"]["tags"]["type"] == "array"
    assert schema["properties"]["tags"]["items"]["type"] == "string"
    assert "enum" in schema["properties"]["unit"]
    assert sorted(schema["properties"]["unit"]["enum"]) == ["celsius", "fahrenheit"]


def test_tool_without_state() -> None:
    registry = ToolRegistry()

    @registry.tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    tool_def = registry.get_tool("add")
    assert tool_def is not None
    assert tool_def.name == "add"
    assert tool_def.description == "Add two numbers."
    assert tool_def.takes_state is False
    assert "state" not in tool_def.parameters_schema["properties"]

    # Direct callable execution
    assert add(2, 3) == 5
    assert tool_def(2, 3) == 5


def test_tool_with_state() -> None:
    registry = ToolRegistry()

    @registry.tool
    def record_event(name: str, state: SimpleState) -> str:
        """Record an event in state."""
        state.counter += 1
        return f"{name}:{state.counter}"

    tool_def = registry.get_tool("record_event")
    assert tool_def is not None
    assert tool_def.takes_state is True
    assert "state" not in tool_def.parameters_schema["properties"]
    assert "name" in tool_def.parameters_schema["properties"]

    state = SimpleState()
    assert record_event("click", state=state) == "click:1"
    assert state.counter == 1


def test_standalone_tool_decorator() -> None:
    @tool(
        name="custom_calc",
        risk=ToolRisk.HIGH,
        effects=frozenset({ToolEffect.WRITE}),
        requires_approval=True,
        timeout=12.5,
    )
    def compute(val: float) -> float:
        """Compute square."""
        return val * val

    assert hasattr(compute, "tool_def")
    td: ToolDef = compute.tool_def
    assert td.name == "custom_calc"
    assert td.risk == ToolRisk.HIGH
    assert td.requires_approval is True
    assert td.timeout == 12.5

    # Direct call works
    assert compute(4.0) == 16.0

    # Registration in ToolRegistry
    reg = ToolRegistry([compute])
    assert "custom_calc" in reg
    assert reg.get_tool("custom_calc") is td


def test_pydantic_output_model_and_serialization() -> None:
    registry = ToolRegistry()

    @registry.tool
    def get_forecast(city: str) -> WeatherReport:
        """Get forecast."""
        return WeatherReport(city=city, temperature=21.5, unit="celsius")

    td = registry.get_tool("get_forecast")
    assert td is not None
    assert td.output_model is WeatherReport
    assert td.output_schema is not None
    assert td.output_schema["type"] == "object"
    assert "temperature" in td.output_schema["properties"]


@pytest.mark.asyncio
async def test_agent_loop_with_tools_list() -> None:
    @tool
    def greet(name: str) -> str:
        """Greet a person."""
        return f"Hello {name}!"

    llm = MockLLM(
        [
            [{"id": "call_1", "name": "greet", "arguments": {"name": "Alice"}}],
            "Task finished.",
        ]
    )

    # agent_loop accepting tools list directly without explicit registry or tool_names
    result = await agent_loop(
        llm,
        system="Concise assistant.",
        context="Greet Alice.",
        tools=[greet],
    )

    assert "finished" in str(result)
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_agent_loop_with_pydantic_return() -> None:
    @tool
    def get_weather(city: str) -> WeatherReport:
        """Get weather."""
        return WeatherReport(city=city, temperature=23.0, unit="celsius")

    llm = MockLLM(
        [
            [{"id": "c1", "name": "get_weather", "arguments": {"city": "Lyon"}}],
            "Weather reported.",
        ]
    )

    result = await agent_loop(
        llm,
        system="Concise assistant.",
        context="Check weather in Lyon.",
        tools=[get_weather],
    )

    assert "reported" in str(result)
    assert result.iterations == 2


def test_pydantic_input_model() -> None:
    def search_records(query: WeatherQuery) -> str:
        """Search records.

        Args:
            query: The search query parameters.
        """
        return f"Results for {query.city}"

    schema, takes_state = infer_tool_schema(search_records)
    assert takes_state is False
    assert "query" in schema["properties"]
    # Schema should either reference or embed the WeatherQuery properties
    assert schema["type"] == "object"
