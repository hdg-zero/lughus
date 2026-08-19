"""Tests for W3-08: provisional and final stream chunk distinction.

Verifies that ``agent_loop_stream()`` yields ``StreamChunk`` for provisional
content and ``LoopResult`` as the single final marker.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from lughus import ToolRegistry
from lughus.loop import LoopResult, StreamChunk, StreamingMode, agent_loop_stream
from lughus.testing import MockStreamingLLM


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


# ── Completed stream: provisional* then LoopResult ──────────────────────────


@pytest.mark.asyncio
async def test_buffered_stream_yields_provisional_then_final(registry: ToolRegistry) -> None:
    """In buffered mode, all provisional chunks precede the single LoopResult."""
    llm = MockStreamingLLM(["Hello world"])
    chunks: list[StreamChunk | LoopResult] = []

    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.BUFFERED,
    ):
        chunks.append(chunk)

    provisionals = [c for c in chunks if isinstance(c, StreamChunk)]
    finals = [c for c in chunks if isinstance(c, LoopResult)]

    assert len(finals) == 1, "Exactly one LoopResult at the end"
    assert chunks[-1] is finals[0], "LoopResult is the last yielded value"
    assert len(provisionals) >= 1, "At least one provisional chunk"
    # All provisional chunks appear before the final LoopResult
    last_provisional_idx = max(i for i, c in enumerate(chunks) if isinstance(c, StreamChunk))
    assert last_provisional_idx < len(chunks) - 1


@pytest.mark.asyncio
async def test_live_stream_yields_provisional_then_final(registry: ToolRegistry) -> None:
    """In live mode, provisional chunks precede the single LoopResult."""
    llm = MockStreamingLLM(["Hello world"])
    chunks: list[StreamChunk | LoopResult] = []

    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.LIVE,
    ):
        chunks.append(chunk)

    provisionals = [c for c in chunks if isinstance(c, StreamChunk)]
    finals = [c for c in chunks if isinstance(c, LoopResult)]

    assert len(finals) == 1
    assert chunks[-1] is finals[0]
    assert len(provisionals) >= 1
    last_provisional_idx = max(i for i, c in enumerate(chunks) if isinstance(c, StreamChunk))
    assert last_provisional_idx < len(chunks) - 1


# ── Provisional chunks have final=False ─────────────────────────────────────


@pytest.mark.asyncio
async def test_provisional_chunks_have_final_false(registry: ToolRegistry) -> None:
    """Every StreamChunk has final=False."""
    llm = MockStreamingLLM(["Some text here"])
    provisionals: list[StreamChunk] = []

    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.LIVE,
    ):
        if isinstance(chunk, StreamChunk):
            provisionals.append(chunk)

    assert len(provisionals) >= 1
    for p in provisionals:
        assert p.final is False, f"StreamChunk {p!r} should have final=False"


@pytest.mark.asyncio
async def test_stream_chunk_content_matches_text(registry: ToolRegistry) -> None:
    """Concatenated provisional content equals the final LoopResult text."""
    llm = MockStreamingLLM(["Alpha Beta Gamma"])
    provisionals: list[StreamChunk] = []
    result: LoopResult | None = None

    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.LIVE,
    ):
        if isinstance(chunk, LoopResult):
            result = chunk
        else:
            assert isinstance(chunk, StreamChunk)
            provisionals.append(chunk)

    assert result is not None
    joined = "".join(c.content for c in provisionals)
    assert joined == str(result)


# ── Interrupted stream emits no LoopResult ──────────────────────────────────


class FailMidStreamLLM:
    """Mock LLM that yields one chunk then raises."""

    model = "test/fail-mid-stream"
    timeout: float | None = None

    async def astream(self, *, messages, tools=None):
        async def _gen():
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Partial", tool_calls=None),
                    )
                ],
                usage=None,
            )
            raise RuntimeError("Connection lost")

        return _gen()


@pytest.mark.asyncio
async def test_interrupted_stream_yields_no_loop_result(registry: ToolRegistry) -> None:
    """When the stream errors mid-flight, no LoopResult is yielded."""
    llm = FailMidStreamLLM()
    collected: list[StreamChunk | LoopResult] = []

    with pytest.raises(RuntimeError, match="Connection lost"):
        async for chunk in agent_loop_stream(
            llm,
            system="sys",
            context="ctx",
            registry=registry,
            tool_names=[],
            streaming_mode=StreamingMode.LIVE,
        ):
            collected.append(chunk)

    assert not any(isinstance(c, LoopResult) for c in collected), (
        "No LoopResult should be yielded on error"
    )
    # But we should have received the partial chunk
    assert len(collected) == 1
    assert isinstance(collected[0], StreamChunk)
    assert collected[0].content == "Partial"


# ── Order invariant: only StreamChunk then LoopResult ────────────────────────


@pytest.mark.asyncio
async def test_no_loop_result_before_provisional_chunks(registry: ToolRegistry) -> None:
    """LoopResult never appears before any StreamChunk."""
    llm = MockStreamingLLM(["One two three"])
    seen_loop_result = False

    async for chunk in agent_loop_stream(
        llm,
        system="sys",
        context="ctx",
        registry=registry,
        tool_names=[],
        streaming_mode=StreamingMode.BUFFERED,
    ):
        if isinstance(chunk, LoopResult):
            seen_loop_result = True
        elif isinstance(chunk, StreamChunk):
            assert not seen_loop_result, "StreamChunk appeared after LoopResult"


# ── StreamChunk dataclass behaviour ─────────────────────────────────────────


def test_stream_chunk_frozen() -> None:
    """StreamChunk is immutable (frozen dataclass)."""
    sc = StreamChunk(content="hello")
    with pytest.raises(AttributeError):
        sc.content = "mutated"  # type: ignore[misc]


def test_stream_chunk_equality() -> None:
    """Two StreamChunks with same content and final flag are equal."""
    a = StreamChunk(content="hello")
    b = StreamChunk(content="hello", final=False)
    assert a == b


def test_stream_chunk_default_final_false() -> None:
    """StreamChunk defaults to final=False."""
    sc = StreamChunk(content="x")
    assert sc.final is False


def test_stream_chunk_is_not_str() -> None:
    """StreamChunk is not a str subclass — it wraps content explicitly."""
    sc = StreamChunk(content="hello")
    assert not isinstance(sc, str)
