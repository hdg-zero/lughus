"""Tests for agent_loop_stream() — the streaming agentic loop.

Covers:
- Direct text response (1 iteration)
- Tool call → text response (2 iterations)
- Parallel tool calls in streaming mode
- Token accumulation (no double-counting — J1-1 regression guard)
- max_iterations enforcement
- LoopResult as last yielded value
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
import pytest

from lughus import ToolRegistry
from lughus.loop import LoopResult, agent_loop_stream
from lughus.testing import MockStreamingLLM


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


# ── Core behaviors ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_direct_text_response(registry: ToolRegistry) -> None:
    """LLM responds with text immediately → text chunks yielded, LoopResult last."""
    llm = MockStreamingLLM(["Hello world!"])
    chunks: list[str | LoopResult] = []

    async for chunk in agent_loop_stream(
        llm, system="You help.", context="Hi",
        registry=registry, tool_names=[], state=None,
    ):
        chunks.append(chunk)

    assert len(chunks) >= 2  # at least one text chunk + LoopResult
    result = chunks[-1]
    assert isinstance(result, LoopResult)
    assert "Hello" in str(result)
    assert result.iterations == 1


@pytest.mark.asyncio
async def test_stream_one_tool_call_then_text(registry: ToolRegistry) -> None:
    """LLM calls a tool, gets result, then streams a text response."""
    llm = MockStreamingLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "World"}}],
        "Greeting done!",
    ])
    text_chunks: list[str] = []
    result: LoopResult | None = None

    async for chunk in agent_loop_stream(
        llm, system="Greet.", context="Say hi to World",
        registry=registry, tool_names=["greet"], state=None,
    ):
        if isinstance(chunk, LoopResult):
            result = chunk
        else:
            text_chunks.append(chunk)

    assert result is not None
    assert result.iterations == 2
    # All streamed chunks concatenated should form the final text
    assert "".join(text_chunks) in str(result)


@pytest.mark.asyncio
async def test_stream_buffers_content_from_tool_call_iterations(registry: ToolRegistry) -> None:
    """Text emitted before a tool call is kept in history but not streamed as final output."""
    usage = SimpleNamespace(
        prompt_tokens=1,
        completion_tokens=1,
        prompt_tokens_details=None,
        _cache_read_input_tokens=0,
    )

    def chunk(content: str | None = None, tool_calls: list | None = None):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=content,
                        tool_calls=tool_calls or [],
                    )
                )
            ],
            usage=None,
        )

    async def first_stream():
        yield chunk(
            content="I will check.",
            tool_calls=[
                SimpleNamespace(
                    index=0,
                    id="c1",
                    function=SimpleNamespace(
                        name="greet",
                        arguments=json.dumps({"name": "World"}),
                    ),
                )
            ],
        )
        yield SimpleNamespace(choices=[], usage=usage)

    async def second_stream():
        yield chunk(content="Final answer.")
        yield SimpleNamespace(choices=[], usage=usage)

    class MixedStreamingLLM:
        model = "test/mixed-stream"
        timeout: float | None = None

        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.streams = [first_stream(), second_stream()]

        async def astream(self, *, messages, tools=None):
            self.calls.append({"messages": messages, "tools": tools})
            return self.streams.pop(0)

    llm = MixedStreamingLLM()
    chunks: list[str | LoopResult] = []

    async for item in agent_loop_stream(
        llm, system="Greet.", context="Say hi to World",
        registry=registry, tool_names=["greet"], state=None,
    ):
        chunks.append(item)

    streamed_text = "".join(item for item in chunks if isinstance(item, str) and not isinstance(item, LoopResult))
    assert streamed_text == "Final answer."
    assert chunks[-1] == "Final answer."
    assistant_messages = [
        message
        for message in llm.calls[-1]["messages"]
        if message["role"] == "assistant" and "tool_calls" in message
    ]
    assert assistant_messages[0]["content"] == "I will check."


@pytest.mark.asyncio
async def test_stream_two_parallel_tool_calls(registry: ToolRegistry) -> None:
    """LLM requests two tools in one chunk — both are executed in parallel."""
    llm = MockStreamingLLM([
        [
            {"id": "c1", "name": "greet", "arguments": {"name": "Alice"}},
            {"id": "c2", "name": "add", "arguments": {"a": 2, "b": 3}},
        ],
        "Done with both tools.",
    ])
    result: LoopResult | None = None

    async for chunk in agent_loop_stream(
        llm, system="Use tools.", context="Greet and add",
        registry=registry, tool_names=["greet", "add"], state=None,
    ):
        if isinstance(chunk, LoopResult):
            result = chunk

    assert result is not None
    assert result.iterations == 2
    # Both tool results should be in the messages sent for the last LLM call
    last_messages = llm.calls[-1]["messages"]
    tool_results = [m for m in last_messages if m["role"] == "tool"]
    assert len(tool_results) == 2


@pytest.mark.asyncio
async def test_stream_loop_result_is_last_yield(registry: ToolRegistry) -> None:
    """The very last yielded value is always a LoopResult (str subclass)."""
    llm = MockStreamingLLM(["Final answer."])
    last_chunk = None

    async for chunk in agent_loop_stream(
        llm, system=".", context=".", registry=registry,
        tool_names=[], state=None,
    ):
        last_chunk = chunk

    assert isinstance(last_chunk, LoopResult)
    assert isinstance(last_chunk, str)


@pytest.mark.asyncio
async def test_stream_max_iterations_raises(registry: ToolRegistry) -> None:
    """Exceeding max_iterations raises RuntimeError in streaming mode."""
    tool_resp = [{"id": "c1", "name": "greet", "arguments": {"name": "x"}}]
    llm = MockStreamingLLM([tool_resp] * 10)

    with pytest.raises(RuntimeError, match="exceeded"):
        async for _ in agent_loop_stream(
            llm, system=".", context=".",
            registry=registry, tool_names=["greet"], state=None,
            max_iterations=3,
        ):
            pass


@pytest.mark.asyncio
async def test_stream_tokens_not_double_counted(registry: ToolRegistry) -> None:
    """J1-1 regression: tokens are counted once even when usage arrives on a
    chunk that also has choices (OpenAI final-chunk pattern).

    MockStreamingLLM sends usage in an empty-choices final chunk, so each
    iteration contributes exactly 10 prompt + 5 completion tokens.
    Two iterations (tool call + text) → 20 prompt + 10 completion total.
    """
    llm = MockStreamingLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "Test"}}],
        "Done.",
    ])
    result: LoopResult | None = None

    async for chunk in agent_loop_stream(
        llm, system=".", context=".",
        registry=registry, tool_names=["greet"], state=None,
    ):
        if isinstance(chunk, LoopResult):
            result = chunk

    assert result is not None
    assert result.prompt_tokens == 20      # 2 iterations × 10
    assert result.completion_tokens == 10  # 2 iterations × 5
    assert result.total_tokens == 30
    assert result.iterations == 2


@pytest.mark.asyncio
async def test_stream_usage_metadata_single_iteration(registry: ToolRegistry) -> None:
    """Single-iteration stream: usage metadata matches one LLM call."""
    llm = MockStreamingLLM(["Hello!"])
    result: LoopResult | None = None

    async for chunk in agent_loop_stream(
        llm, system=".", context=".",
        registry=registry, tool_names=[], state=None,
    ):
        if isinstance(chunk, LoopResult):
            result = chunk

    assert result is not None
    assert result.iterations == 1
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.elapsed >= 0


@pytest.mark.asyncio
async def test_stream_tool_call_content_none_not_in_message(registry: ToolRegistry) -> None:
    """Streaming tool-call messages must not include content=None."""
    llm = MockStreamingLLM([
        [{"id": "c1", "name": "greet", "arguments": {"name": "Azure"}}],
        "Done.",
    ])

    async for _ in agent_loop_stream(
        llm, system=".", context=".",
        registry=registry, tool_names=["greet"], state=None,
    ):
        pass

    for call in llm.calls:
        for msg in call["messages"]:
            if msg["role"] == "assistant" and "tool_calls" in msg:
                if "content" in msg:
                    assert msg["content"] is not None


@pytest.mark.asyncio
async def test_stream_next_chunk_timeout(registry: ToolRegistry) -> None:
    """Streaming stalls are bounded while waiting for the next chunk."""
    class HangingStreamingLLM:
        model = "test/hanging-stream"
        timeout: float | None = 0.01

        async def astream(self, *, messages, tools=None):
            async def _aiter():
                await asyncio.sleep(1)
                yield None
            return _aiter()

    with pytest.raises(asyncio.TimeoutError):
        async for _ in agent_loop_stream(
            HangingStreamingLLM(),
            system=".",
            context=".",
            registry=registry,
            tool_names=[],
            state=None,
        ):
            pass
