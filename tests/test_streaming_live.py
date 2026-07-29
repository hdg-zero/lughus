"""Tests for live / live_at_most_once streaming mode (M3-03)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lughus import ToolRegistry
from lughus.loop import LoopResult, StreamingMode, agent_loop_stream
from lughus.testing import MockStreamingLLM


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


@pytest.mark.asyncio
async def test_invalid_streaming_mode_raises(registry: ToolRegistry) -> None:
    llm = MockStreamingLLM(["Hello"])
    with pytest.raises(ValueError, match="streaming_mode must be 'buffered' or 'live'"):
        async for _ in agent_loop_stream(
            llm,
            system="sys",
            context="ctx",
            registry=registry,
            tool_names=[],
            streaming_mode="invalid_mode",
        ):
            pass


@pytest.mark.asyncio
async def test_live_streaming_yields_chunks_immediately(registry: ToolRegistry) -> None:
    llm = MockStreamingLLM(["Hello world"])
    chunks = []
    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.LIVE,
    ):
        chunks.append(chunk)

    # 2 text chunks ('Hello', ' world') + 1 final LoopResult
    assert len(chunks) == 3
    assert chunks[:2] == ["Hello", " world"]
    assert isinstance(chunks[2], LoopResult)
    assert str(chunks[2]) == "Hello world"


@pytest.mark.asyncio
async def test_live_at_most_once_alias(registry: ToolRegistry) -> None:
    llm = MockStreamingLLM(["Live stream"])
    chunks = []
    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.LIVE_AT_MOST_ONCE,
    ):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[:2] == ["Live", " stream"]
    assert isinstance(chunks[2], LoopResult)


class FailingStreamLLM:
    """Mock LLM that emits a chunk and then fails with a transient error."""

    def __init__(self) -> None:
        self.model = "mock-failing"
        self.max_retries = 2
        self.retry_base_delay = 0.01

    async def astream(self, messages: list[dict], tools: list[dict]):
        async def _gen():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(delta=SimpleNamespace(content="Partial text", tool_calls=None))
                ]
            )
            raise TimeoutError("Connection reset mid-stream")

        return _gen()


@pytest.mark.asyncio
async def test_live_mode_no_retry_after_first_emitted_chunk(registry: ToolRegistry) -> None:
    """In live_at_most_once mode, once a chunk is emitted to the caller, retries are disabled."""
    llm = FailingStreamLLM()
    emitted = []
    with pytest.raises(TimeoutError):
        async for chunk in agent_loop_stream(
            llm,
            system="sys",
            context="ctx",
            registry=registry,
            tool_names=[],
            streaming_mode=StreamingMode.LIVE,
        ):
            emitted.append(chunk)

    # First chunk was yielded before exception, no duplicate retries
    assert emitted == ["Partial text"]
