"""W3-04: stable prefix guarantee — byte-identical across turns.

Verifies that the cacheable prefix (system + context items + user objective)
and the frozen tool declarations remain byte-identical across every LLM call
in a multi-turn agent_loop run.  Also confirms that changing the tool set
produces a different prefix (non-trivially constant).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from lughus import ToolRegistry
from lughus.context import ContextItem, TrustLevel
from lughus.loop import agent_loop
from lughus.testing import MockLLM


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool(
        "echo",
        "Echo input.",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    def echo(*, text: str, state) -> str:
        return json.dumps({"echo": text})

    @r.tool(
        "add",
        "Add two numbers.",
        {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    )
    def add(*, a: int, b: int, state) -> str:
        return json.dumps({"sum": a + b})

    return r


def _make_items() -> list[ContextItem]:
    return [
        ContextItem(
            role="user",
            content="External data from API",
            source="api-gateway",
            trust=TrustLevel.EXTERNAL,
            id="ext-001",
        ),
        ContextItem(
            role="user",
            content="User preference: dark mode",
            source="profile-service",
            trust=TrustLevel.USER,
            id="usr-002",
        ),
    ]


# ── Byte-identical prefix across turns ──────────────────────────────────────


def _serialize_prefix(messages: list[dict], prefix_len: int) -> str:
    """Canonical JSON serialization of the first *prefix_len* messages."""
    return json.dumps(
        messages[:prefix_len],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


@pytest.mark.asyncio
async def test_prefix_byte_identical_across_5_turns(registry: ToolRegistry) -> None:
    """Prefix (system + user objective) must be byte-identical across all
    turns in a 5-turn run (4 tool calls + 1 text response)."""
    llm = MockLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "a"}}],
            [{"id": "c2", "name": "echo", "arguments": {"text": "b"}}],
            [{"id": "c3", "name": "add", "arguments": {"a": 1, "b": 2}}],
            [{"id": "c4", "name": "echo", "arguments": {"text": "c"}}],
            "Done.",
        ]
    )

    await agent_loop(
        llm,
        system="You are a test agent.",
        context="Run some tools.",
        registry=registry,
        tool_names=["echo", "add"],
    )

    assert len(llm.calls) == 5
    prefix_len = 2  # system + user objective, no context items

    prefix_turn_1 = _serialize_prefix(llm.calls[0]["messages"], prefix_len)
    for i in range(1, len(llm.calls)):
        prefix_turn_i = _serialize_prefix(llm.calls[i]["messages"], prefix_len)
        assert prefix_turn_1 == prefix_turn_i, (
            f"Prefix diverged between turn 1 and turn {i + 1}"
        )


@pytest.mark.asyncio
async def test_prefix_byte_identical_with_context_items(
    registry: ToolRegistry,
) -> None:
    """Prefix including context items must be byte-identical across turns."""
    items = _make_items()
    llm = MockLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "x"}}],
            [{"id": "c2", "name": "echo", "arguments": {"text": "y"}}],
            "Finished.",
        ]
    )

    await agent_loop(
        llm,
        system="Agent.",
        context="Do things.",
        registry=registry,
        tool_names=["echo"],
        context_items=items,
    )

    assert len(llm.calls) == 3
    # system + context_items block + user objective = 3
    prefix_len = 3

    prefix_turn_1 = _serialize_prefix(llm.calls[0]["messages"], prefix_len)
    prefix_turn_3 = _serialize_prefix(llm.calls[2]["messages"], prefix_len)
    assert prefix_turn_1 == prefix_turn_3


# ── Tools are also stable across turns ──────────────────────────────────────


@pytest.mark.asyncio
async def test_tools_identical_across_turns(registry: ToolRegistry) -> None:
    """Frozen tool declarations must be the same object across all turns."""
    llm = MockLLM(
        [
            [{"id": "c1", "name": "echo", "arguments": {"text": "a"}}],
            [{"id": "c2", "name": "add", "arguments": {"a": 1, "b": 2}}],
            "OK.",
        ]
    )

    await agent_loop(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=["echo", "add"],
    )

    assert len(llm.calls) == 3
    tools_turn_1 = json.dumps(
        llm.calls[0]["tools"], sort_keys=True, separators=(",", ":"),
    )
    for i in range(1, len(llm.calls)):
        tools_turn_i = json.dumps(
            llm.calls[i]["tools"], sort_keys=True, separators=(",", ":"),
        )
        assert tools_turn_1 == tools_turn_i, (
            f"Tool declarations diverged between turn 1 and turn {i + 1}"
        )


# ── Adding a tool CHANGES the prefix ───────────────────────────────────────


@pytest.mark.asyncio
async def test_adding_tool_changes_declarations() -> None:
    """Registering a new tool must produce different declarations --
    the prefix is not trivially constant."""
    r1 = ToolRegistry()

    @r1.tool(
        "echo",
        "Echo.",
        {"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"]},
    )
    def echo1(*, t: str, state) -> str:
        return t

    decl_before = r1.declarations_json(["echo"])

    r2 = ToolRegistry()

    @r2.tool(
        "echo",
        "Echo.",
        {"type": "object", "properties": {"t": {"type": "string"}}, "required": ["t"]},
    )
    def echo2(*, t: str, state) -> str:
        return t

    @r2.tool(
        "greet",
        "Greet.",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    )
    def greet(*, name: str, state) -> str:
        return f"Hello {name}"

    decl_after = r2.declarations_json(["echo", "greet"])

    assert decl_before != decl_after, (
        "Declarations did not change after adding a tool"
    )


# ── PYTHONHASHSEED independence ─────────────────────────────────────────────

# The inline script that each subprocess executes.  It runs agent_loop with
# two tool-call turns and prints the serialized prefix from turn 1 and turn 3.
_HASHSEED_SCRIPT = textwrap.dedent("""\
    import asyncio, json, sys
    from lughus import ToolRegistry
    from lughus.loop import agent_loop
    from lughus.testing import MockLLM

    async def _run():
        r = ToolRegistry()

        @r.tool("ping", "Ping.", {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        })
        def ping(*, x: str, state) -> str:
            return json.dumps({"pong": x})

        llm = MockLLM([
            [{"id": "c1", "name": "ping", "arguments": {"x": "1"}}],
            [{"id": "c2", "name": "ping", "arguments": {"x": "2"}}],
            "done",
        ])
        await agent_loop(
            llm,
            system="sys",
            context="ctx",
            registry=r,
            tool_names=["ping"],
        )
        prefix_1 = json.dumps(llm.calls[0]["messages"][:2],
                              sort_keys=True, separators=(",", ":"))
        prefix_3 = json.dumps(llm.calls[2]["messages"][:2],
                              sort_keys=True, separators=(",", ":"))
        tools_1 = json.dumps(llm.calls[0]["tools"],
                             sort_keys=True, separators=(",", ":"))
        tools_3 = json.dumps(llm.calls[2]["tools"],
                             sort_keys=True, separators=(",", ":"))
        print(prefix_1)
        print(prefix_3)
        print(tools_1)
        print(tools_3)

    asyncio.run(_run())
""")


@pytest.mark.parametrize("seed", ["0", "12345"])
def test_prefix_stable_under_different_pythonhashseed(seed: str) -> None:
    """Prefix must be byte-identical across turns regardless of PYTHONHASHSEED."""
    result = subprocess.run(
        [sys.executable, "-c", _HASHSEED_SCRIPT],
        capture_output=True,
        text=True,
        env={**{"PYTHONHASHSEED": seed, "SYSTEMROOT": "C:\\Windows"},
             "PATH": subprocess.os.environ.get("PATH", "")},
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Subprocess failed (seed={seed}):\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    lines = result.stdout.strip().split("\n")
    assert len(lines) == 4, f"Expected 4 lines, got {len(lines)}"
    prefix_1, prefix_3, tools_1, tools_3 = lines
    assert prefix_1 == prefix_3, (
        f"Prefix diverged under PYTHONHASHSEED={seed}"
    )
    assert tools_1 == tools_3, (
        f"Tool declarations diverged under PYTHONHASHSEED={seed}"
    )


def test_prefix_identical_across_two_hashseeds() -> None:
    """The same inputs must produce byte-identical prefix regardless of hash seed."""
    outputs: dict[str, list[str]] = {}
    for seed in ["0", "99999"]:
        result = subprocess.run(
            [sys.executable, "-c", _HASHSEED_SCRIPT],
            capture_output=True,
            text=True,
            env={**{"PYTHONHASHSEED": seed, "SYSTEMROOT": "C:\\Windows"},
                 "PATH": subprocess.os.environ.get("PATH", "")},
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Subprocess failed (seed={seed}):\n{result.stderr}"
        )
        outputs[seed] = result.stdout.strip().split("\n")

    # Prefix and tools from seed=0 must match seed=99999
    assert outputs["0"][0] == outputs["99999"][0], (
        "Prefix differs between PYTHONHASHSEED=0 and PYTHONHASHSEED=99999"
    )
    assert outputs["0"][2] == outputs["99999"][2], (
        "Tools differ between PYTHONHASHSEED=0 and PYTHONHASHSEED=99999"
    )


# ── Cache metrics forwarding ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_metrics_forwarded_to_loop_result(
    registry: ToolRegistry,
) -> None:
    """LoopResult.cached_tokens must reflect cache_read_input_tokens from usage."""
    from lughus.testing import FakeUsage

    class CachingMockLLM(MockLLM):
        """MockLLM that attaches cache fields to usage."""

        async def generate(self, *, messages, tools=None):
            resp = await super().generate(messages=messages, tools=tools)
            # Replace usage with one carrying cache fields
            patched = resp.__class__(
                choices=resp.choices,
                usage=FakeUsage(
                    prompt_tokens=100,
                    completion_tokens=20,
                    cache_read_input_tokens=80,
                    cache_creation_input_tokens=15,
                ),
                model=resp.model,
            )
            return patched

    llm = CachingMockLLM(["Cache test done."])
    result = await agent_loop(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
    )

    # cached_tokens should include the cache_read_input_tokens
    assert result.cached_tokens == 80
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 20
