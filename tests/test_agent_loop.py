"""Tests for agent_loop() — the core agentic loop."""
from __future__ import annotations

import json
import pytest

from lughus import LughusError, ToolRegistry
from lughus.loop import LoopResult, ToolExecutionConfig, _extract_usage, agent_loop
from lughus.testing import MockLLM


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()

    @r.tool("greet", "Greet by name.", {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    })
    def greet(*, name: str, state) -> str:
        return json.dumps({"greeting": f"Hello {name}!"})

    @r.tool("add", "Add two numbers.", {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    })
    def add(*, a: int, b: int, state) -> str:
        return json.dumps({"result": a + b})

    return r


def test_extract_usage_supports_dict_payloads() -> None:
    usage = {
        "prompt_tokens": 12,
        "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 3},
        "_cache_read_input_tokens": 2,
    }

    assert _extract_usage(usage) == (12, 5, 5)


def test_loop_result_reports_uncached_prompt_tokens() -> None:
    result = LoopResult(
        "ok",
        iterations=1,
        elapsed=0.0,
        prompt_tokens=100,
        completion_tokens=20,
        cached_tokens=85,
    )

    assert result.uncached_prompt_tokens == 15
    assert result.total_tokens == 120


# ── Core behaviors ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_direct_text_response(registry: ToolRegistry) -> None:
    """LLM responds with text immediately → LoopResult with 1 iteration."""
    llm = MockLLM(["Hello, I'm ready to help!"])
    result = await agent_loop(
        llm, system="You help.", context="Hi", registry=registry,
        tool_names=["greet"], state=None,
    )
    assert isinstance(result, LoopResult)
    assert result == "Hello, I'm ready to help!"
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_one_tool_call_then_text(registry: ToolRegistry) -> None:
    """LLM calls one tool, gets result, then responds with text."""
    llm = MockLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "World"}}],
        "Greeting done: Hello World!",
    ])
    result = await agent_loop(
        llm, system="Greet the user.", context="Say hi to World",
        registry=registry, tool_names=["greet"], state=None,
    )
    assert "Greeting done" in result
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_two_parallel_tool_calls(registry: ToolRegistry) -> None:
    """LLM requests two tools in one round-trip — both are executed."""
    llm = MockLLM([
        [
            {"id": "c1", "name": "greet", "arguments": {"name": "Alice"}},
            {"id": "c2", "name": "add", "arguments": {"a": 3, "b": 4}},
        ],
        "Done with both tools.",
    ])
    result = await agent_loop(
        llm, system="Use tools.", context="Greet and add",
        registry=registry, tool_names=["greet", "add"], state=None,
    )
    assert result.iterations == 2
    # Both tool results should be in the messages sent to the LLM
    last_call_messages = llm.calls[-1]["messages"]
    tool_results = [m for m in last_call_messages if m["role"] == "tool"]
    assert len(tool_results) == 2


@pytest.mark.asyncio
async def test_unknown_declared_tool_name_raises(registry: ToolRegistry) -> None:
    """A misconfigured tool_names list fails before the first LLM request."""
    llm = MockLLM(["This should not be used"])

    with pytest.raises(Exception, match="not registered"):
        await agent_loop(
            llm, system=".", context=".", registry=registry,
            tool_names=["missing"], state=None,
        )

    assert llm.calls == []


@pytest.mark.asyncio
async def test_max_iterations_raises(registry: ToolRegistry) -> None:
    """Exceeding max_iterations raises RuntimeError."""
    # Always returns a tool call → infinite loop
    tool_response = [{"id": "c1", "name": "greet", "arguments": {"name": "x"}}]
    llm = MockLLM([tool_response] * 10)

    with pytest.raises((RuntimeError, LughusError), match="exceeded") as exc_info:
        await agent_loop(
            llm, system="Loop.", context="Go",
            registry=registry, tool_names=["greet"], state=None,
            max_iterations=3,
        )
    assert isinstance(exc_info.value, LughusError)


@pytest.mark.asyncio
async def test_message_history_size_limit_prevents_llm_call(registry: ToolRegistry) -> None:
    """Oversized message history fails before sending a request to the LLM."""
    llm = MockLLM(["This should not be used"])

    with pytest.raises(RuntimeError, match="message history exceeded"):
        await agent_loop(
            llm,
            system="system",
            context="x" * 50,
            registry=registry,
            tool_names=["greet"],
            state=None,
            tool_config=ToolExecutionConfig(max_message_history_chars=10),
        )

    assert llm.calls == []


@pytest.mark.asyncio
async def test_loop_result_is_str_subclass(registry: ToolRegistry) -> None:
    """LoopResult behaves as a str in all string contexts."""
    llm = MockLLM(['{"status": "ok"}'])
    result = await agent_loop(
        llm, system=".", context=".", registry=registry,
        tool_names=[], state=None,
    )
    assert isinstance(result, str)
    assert json.loads(result) == {"status": "ok"}


@pytest.mark.asyncio
async def test_usage_metadata_accumulated(registry: ToolRegistry) -> None:
    """Token counts accumulate across all LLM iterations."""
    llm = MockLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "Test"}}],
        "Done.",
    ])
    result = await agent_loop(
        llm, system=".", context=".", registry=registry,
        tool_names=["greet"], state=None,
    )
    # MockLLM: call 1 (tool) = 15 prompt + 8 completion
    #          call 2 (text) = 10 prompt + 5 completion
    # Total: 25 prompt, 13 completion, 38 total
    assert result.prompt_tokens == 25
    assert result.completion_tokens == 13
    assert result.total_tokens == 38
    assert result.uncached_prompt_tokens == 25
    assert result.iterations == 2
    assert result.elapsed >= 0


@pytest.mark.asyncio
async def test_compact_tool_schema_removes_parameter_descriptions() -> None:
    r = ToolRegistry()

    @r.tool(
        "describe",
        "Describe a thing.",
        {
            "type": "object",
            "description": "Verbose root description.",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Verbose property description.",
                }
            },
            "required": ["name"],
        },
    )
    def describe(*, name: str, state) -> str:
        return name

    llm = MockLLM(["Done."])

    await agent_loop(
        llm,
        system=".",
        context=".",
        registry=r,
        tool_names=["describe"],
        state=None,
        tool_config=ToolExecutionConfig(compact_tool_schemas=True),
    )

    tool = llm.calls[0]["tools"][0]
    assert tool["function"]["description"] == "Describe a thing."
    assert "description" not in tool["function"]["parameters"]
    assert "description" not in tool["function"]["parameters"]["properties"]["name"]


@pytest.mark.asyncio
async def test_state_passed_to_tools(registry: ToolRegistry) -> None:
    """The state object is correctly forwarded to tool functions."""
    class State:
        received_name: str = ""

    state = State()

    r = ToolRegistry()

    @r.tool("capture", "Capture name.", {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    })
    def capture(*, name: str, state: State) -> str:
        state.received_name = name
        return json.dumps({"ok": True})

    llm = MockLLM([
        [{"id": "c1", "name": "capture", "arguments": {"name": "Lughus"}}],
        "Captured.",
    ])
    await agent_loop(
        llm, system=".", context=".", registry=r,
        tool_names=["capture"], state=state,
    )
    assert state.received_name == "Lughus"


@pytest.mark.asyncio
async def test_tool_can_return_dict(registry: ToolRegistry) -> None:
    """Non-string tool outputs are JSON-serialized before being sent to the LLM."""
    r = ToolRegistry()

    @r.tool("dict_tool", "Return a dict.", {"type": "object", "properties": {}})
    def dict_tool(*, state) -> dict:
        return {"ok": True}

    llm = MockLLM([
        [{"id": "c1", "name": "dict_tool", "arguments": {}}],
        "Done.",
    ])

    await agent_loop(
        llm, system=".", context=".", registry=r,
        tool_names=["dict_tool"],
    )

    tool_messages = [m for m in llm.calls[-1]["messages"] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"]) == {"ok": True}


@pytest.mark.asyncio
async def test_tool_call_content_none_not_in_message(registry: ToolRegistry) -> None:
    """J1-3: When msg.content is None during a tool call, the 'content' key is
    omitted from the assistant message — prevents 400 errors on Azure OpenAI and
    other strict providers that reject null content."""
    llm = MockLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "Azure"}}],
        "Done.",
    ])
    await agent_loop(
        llm, system=".", context=".", registry=registry,
        tool_names=["greet"], state=None,
    )
    # Inspect all assistant messages in the conversation history
    for call in llm.calls:
        for msg in call["messages"]:
            if msg["role"] == "assistant" and "tool_calls" in msg:
                # content key must be absent (not None) when there's no content
                if "content" in msg:
                    assert msg["content"] is not None, (
                        "Assistant message has 'content': None — breaks Azure OpenAI"
                    )
