"""Four benchmark scenarios measuring lughus framework overhead.

Each scenario function returns a dict with metrics:
    tokens_in, tokens_out, provider_calls, wall_time_s, cpu_time_s, prefix_size_bytes
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

from lughus import ToolRegistry
from lughus.loop import agent_loop

from .provider import build_mock_llm


def _measure_prefix(system: str, context: str) -> int:
    """Estimate the byte size of the cacheable prefix (system + context)."""
    return len(system.encode("utf-8")) + len(context.encode("utf-8"))


def _compute_prefix_reuse(llm: Any) -> float:
    """Return the percentage of turns whose prefix was byte-identical to turn 1.

    W3-04: measures prefix stability across LLM calls.  The prefix is the
    first two messages (system + user objective) for benchmark scenarios that
    do not use context_items.
    """
    calls = getattr(llm, "calls", None)
    if not calls or len(calls) < 2:
        return 100.0

    prefix_len = 2  # system + user objective (no context_items in benchmarks)
    first_prefix = json.dumps(
        calls[0]["messages"][:prefix_len],
        sort_keys=True,
        separators=(",", ":"),
    )
    matching = 1  # turn 1 matches itself
    for call in calls[1:]:
        prefix = json.dumps(
            call["messages"][:prefix_len],
            sort_keys=True,
            separators=(",", ":"),
        )
        if prefix == first_prefix:
            matching += 1
    return round(100.0 * matching / len(calls), 1)


async def _run_scenario(
    name: str,
    llm: Any,
    system: str,
    context: str,
    registry: ToolRegistry,
    tool_names: list[str],
    max_iterations: int = 12,
) -> dict[str, Any]:
    """Run a single scenario and collect metrics."""
    prefix_size_bytes = _measure_prefix(system, context)

    cpu_start = time.process_time()
    wall_start = time.perf_counter()

    result = await agent_loop(
        llm,
        system=system,
        context=context,
        registry=registry,
        tool_names=tool_names,
        state=None,
        max_iterations=max_iterations,
    )

    wall_end = time.perf_counter()
    cpu_end = time.process_time()

    # W3-04: measure prefix reuse across turns.
    prefix_reuse_pct = _compute_prefix_reuse(llm)

    return {
        "scenario": name,
        "tokens_in": result.prompt_tokens,
        "tokens_out": result.completion_tokens,
        "provider_calls": result.iterations,
        "wall_time_s": round(wall_end - wall_start, 6),
        "cpu_time_s": round(cpu_end - cpu_start, 6),
        "prefix_size_bytes": prefix_size_bytes,
        "prefix_reuse_pct": prefix_reuse_pct,
    }


# ---------------------------------------------------------------------------
# Scenario helpers
# ---------------------------------------------------------------------------


def _make_echo_registry(count: int = 1, output_size: int = 32) -> tuple[ToolRegistry, list[str]]:
    """Create a registry with ``count`` echo tools, each returning ``output_size`` bytes."""
    r = ToolRegistry()
    names: list[str] = []
    for i in range(count):
        tool_name = f"echo_{i}"
        names.append(tool_name)
        # The output payload is generated at call time based on output_size.
        # We capture output_size via default arg to avoid late-binding issues.
        @r.tool(
            tool_name,
            f"Echo tool {i}.",
            {
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        )
        def _echo(*, input: str, state: Any, _size: int = output_size) -> str:
            payload = "x" * max(0, _size - 20)
            return json.dumps({"result": payload})

    return r, names


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SYSTEM = "You are a benchmark agent."
CONTEXT = "Execute the benchmark task."


async def scenario_short() -> dict[str, Any]:
    """3-turn run: LLM -> tool -> LLM -> tool -> LLM -> text."""
    registry, tool_names = _make_echo_registry(count=1)
    responses: list[Any] = [
        [{"id": "c1", "name": "echo_0", "arguments": {"input": "a"}}],
        [{"id": "c2", "name": "echo_0", "arguments": {"input": "b"}}],
        "Benchmark complete.",
    ]
    llm = build_mock_llm(responses)
    return await _run_scenario(
        "short", llm, SYSTEM, CONTEXT, registry, tool_names, max_iterations=12,
    )


async def scenario_long() -> dict[str, Any]:
    """12-turn run: 11 tool calls then a text response."""
    registry, tool_names = _make_echo_registry(count=1)
    responses: list[Any] = [
        [{"id": f"c{i}", "name": "echo_0", "arguments": {"input": f"turn_{i}"}}]
        for i in range(11)
    ]
    responses.append("Long benchmark complete.")
    llm = build_mock_llm(responses)
    return await _run_scenario(
        "long", llm, SYSTEM, CONTEXT, registry, tool_names, max_iterations=12,
    )


async def scenario_large_outputs() -> dict[str, Any]:
    """3-turn run with tools returning ~10KB each."""
    registry, tool_names = _make_echo_registry(count=1, output_size=10_240)
    responses: list[Any] = [
        [{"id": "c1", "name": "echo_0", "arguments": {"input": "big_a"}}],
        [{"id": "c2", "name": "echo_0", "arguments": {"input": "big_b"}}],
        "Large output benchmark complete.",
    ]
    llm = build_mock_llm(responses)
    return await _run_scenario(
        "large_outputs", llm, SYSTEM, CONTEXT, registry, tool_names, max_iterations=12,
    )


async def scenario_many_tools() -> dict[str, Any]:
    """Single tool call with 40 tools declared in the registry."""
    registry, tool_names = _make_echo_registry(count=40)
    responses: list[Any] = [
        [{"id": "c1", "name": "echo_0", "arguments": {"input": "pick_one"}}],
        "Many tools benchmark complete.",
    ]
    llm = build_mock_llm(responses)
    return await _run_scenario(
        "many_tools", llm, SYSTEM, CONTEXT, registry, tool_names, max_iterations=12,
    )


ALL_SCENARIOS = {
    "short": scenario_short,
    "long": scenario_long,
    "large_outputs": scenario_large_outputs,
    "many_tools": scenario_many_tools,
}

EXPECTED_METRIC_KEYS = frozenset(
    ["scenario", "tokens_in", "tokens_out", "provider_calls",
     "wall_time_s", "cpu_time_s", "prefix_size_bytes", "prefix_reuse_pct"]
)
