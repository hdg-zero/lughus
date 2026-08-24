"""Artifact projection — large tool outputs stored as artifacts,
replaced in history by a short reference + summary.  ``fetch_artifact``
built-in tool retrieves full content.  Disabled by default.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from lughus import ToolRegistry
from lughus.core.artifacts import ArtifactStore, _summarize
from lughus.infra.runtime import ExecutionRuntime, RuntimeConfig
from lughus.loop import ToolExecutionConfig
from lughus.loop import _execute_tools as _raw_execute_tools
from lughus.loop._loop import (
    _FETCH_ARTIFACT_TOOL,
    _active_artifact_store,
    _setup_artifact_projection,
)

# ── helpers ──────────────────────────────────────────────────────────


def _test_runtime(max_workers: int = 32) -> ExecutionRuntime:
    return ExecutionRuntime(RuntimeConfig(max_sync_workers=max_workers))


async def _execute_tools(
    tool_calls: list[tuple[str, str, str]],
    registry: ToolRegistry,
    state: Any = None,
    config: ToolExecutionConfig | None = None,
) -> list[tuple[str, str]]:
    runtime_to_close: ExecutionRuntime | None = None
    if config is None:
        runtime_to_close = _test_runtime()
        config = ToolExecutionConfig(runtime=runtime_to_close)
    elif config.runtime is None:
        runtime_to_close = _test_runtime()
        config = dataclasses.replace(config, runtime=runtime_to_close)
    try:
        return await _raw_execute_tools(tool_calls, registry, state, config=config)
    finally:
        if runtime_to_close is not None:
            await runtime_to_close.close()


def _make_large_output(size: int = 5000) -> str:
    """Return a JSON string exceeding the default projection threshold."""
    return json.dumps({"data": "x" * size})


def _registry_with_large_tool(output_size: int = 5000) -> ToolRegistry:
    """Create a registry with a tool that returns a large output."""
    registry = ToolRegistry()

    @registry.tool(
        "big_tool",
        "Returns a large output.",
        {"type": "object", "properties": {}},
    )
    def big_tool(*, state: Any) -> str:
        return _make_large_output(output_size)

    return registry


def _registry_with_small_tool() -> ToolRegistry:
    """Create a registry with a tool that returns a small output."""
    registry = ToolRegistry()

    @registry.tool(
        "small_tool",
        "Returns a small output.",
        {"type": "object", "properties": {}},
    )
    def small_tool(*, state: Any) -> str:
        return json.dumps({"status": "ok"})

    return registry


# ── 1. ArtifactStore unit tests ──────────────────────────────────────


class TestArtifactStore:
    def test_store_and_fetch(self) -> None:
        store = ArtifactStore()
        content = "hello world"
        aid = store.store_artifact(content)
        assert store.fetch_artifact(aid) == content

    def test_fetch_with_offset(self) -> None:
        store = ArtifactStore()
        content = "abcdefghij"
        aid = store.store_artifact(content)
        assert store.fetch_artifact(aid, offset=3) == "defghij"

    def test_fetch_with_length(self) -> None:
        store = ArtifactStore()
        content = "abcdefghij"
        aid = store.store_artifact(content)
        assert store.fetch_artifact(aid, length=5) == "abcde"

    def test_fetch_with_offset_and_length(self) -> None:
        store = ArtifactStore()
        content = "abcdefghij"
        aid = store.store_artifact(content)
        assert store.fetch_artifact(aid, offset=2, length=4) == "cdef"

    def test_fetch_unknown_raises(self) -> None:
        store = ArtifactStore()
        with pytest.raises(KeyError):
            store.fetch_artifact("nonexistent")

    def test_contains(self) -> None:
        store = ArtifactStore()
        aid = store.store_artifact("data")
        assert aid in store
        assert "missing" not in store

    def test_len(self) -> None:
        store = ArtifactStore()
        assert len(store) == 0
        store.store_artifact("a")
        store.store_artifact("b")
        assert len(store) == 2


# ── 2. _summarize unit tests ────────────────────────────────────────


class TestSummarize:
    def test_json_object(self) -> None:
        content = json.dumps({"name": "alice", "age": 30})
        summary = _summarize(content)
        assert summary["type"] == "json_object"
        assert "name" in summary["keys"]
        assert "age" in summary["keys"]
        assert summary["size"] == len(content)

    def test_json_array(self) -> None:
        content = json.dumps([1, 2, 3])
        summary = _summarize(content)
        assert summary["type"] == "json_array"
        assert summary["length"] == 3

    def test_json_scalar(self) -> None:
        content = json.dumps(42)
        summary = _summarize(content)
        assert summary["type"] == "json_scalar"

    def test_plain_text(self) -> None:
        content = "Hello, this is plain text."
        summary = _summarize(content)
        assert summary["type"] == "text"
        assert summary["size"] == len(content)
        assert summary["preview"].startswith("Hello")

    def test_long_text_preview_truncated(self) -> None:
        content = "x" * 500
        summary = _summarize(content)
        assert summary["preview"].endswith("...")
        # Preview should be 200 chars + "..."
        assert len(summary["preview"]) == 203


# ── 3. Projection enabled — above threshold ─────────────────────────


@pytest.mark.asyncio
async def test_above_threshold_projects_artifact() -> None:
    """When artifact projection is enabled and output exceeds threshold,
    history contains a reference instead of the full content."""
    registry = _registry_with_large_tool(5000)
    store = ArtifactStore()
    config = ToolExecutionConfig(
        artifact_projection=True,
        artifact_projection_threshold=100,
        artifact_store=store,
    )
    token = _active_artifact_store.set(store)
    try:
        results = await _execute_tools(
            [("tc1", "big_tool", "")],
            registry,
            config=config,
        )
    finally:
        _active_artifact_store.reset(token)

    assert len(results) == 1
    _tc_id, output = results[0]
    parsed = json.loads(output)

    assert parsed["ok"] is True
    assert "artifact_id" in parsed
    assert "summary" in parsed
    assert parsed["hint"] == "Use fetch_artifact to retrieve full content"

    # The full content must NOT be in the output
    assert "result" not in parsed

    # The artifact should be stored
    aid = parsed["artifact_id"]
    assert aid in store
    full = store.fetch_artifact(aid)
    full_parsed = json.loads(full)
    assert full_parsed["ok"] is True
    assert "result" in full_parsed


# ── 4. Projection enabled — below threshold ─────────────────────────


@pytest.mark.asyncio
async def test_below_threshold_no_projection() -> None:
    """When output is below the threshold, no projection occurs even
    when artifact_projection is enabled."""
    registry = _registry_with_small_tool()
    store = ArtifactStore()
    config = ToolExecutionConfig(
        artifact_projection=True,
        artifact_projection_threshold=4096,
        artifact_store=store,
    )
    token = _active_artifact_store.set(store)
    try:
        results = await _execute_tools(
            [("tc1", "small_tool", "")],
            registry,
            config=config,
        )
    finally:
        _active_artifact_store.reset(token)

    assert len(results) == 1
    _tc_id, output = results[0]
    parsed = json.loads(output)

    # Should be a normal result, no artifact reference
    assert parsed["ok"] is True
    assert "result" in parsed
    assert "artifact_id" not in parsed

    # No artifacts stored
    assert len(store) == 0


# ── 5. Projection disabled — full output in history ──────────────────


@pytest.mark.asyncio
async def test_disabled_full_output() -> None:
    """When artifact_projection is False (default), full output is kept
    in history regardless of size."""
    registry = _registry_with_large_tool(5000)
    config = ToolExecutionConfig(
        artifact_projection=False,
    )
    results = await _execute_tools(
        [("tc1", "big_tool", "")],
        registry,
        config=config,
    )

    assert len(results) == 1
    _tc_id, output = results[0]
    parsed = json.loads(output)

    # Full result present, no artifact reference
    assert parsed["ok"] is True
    assert "result" in parsed
    assert "artifact_id" not in parsed


# ── 6. fetch_artifact tool returns exact content ─────────────────────


@pytest.mark.asyncio
async def test_fetch_artifact_tool_returns_content() -> None:
    """The fetch_artifact built-in tool retrieves stored artifacts."""
    registry = ToolRegistry()
    tool_names: list[str] = []

    cfg = ToolExecutionConfig(artifact_projection=True)
    cfg = _setup_artifact_projection(registry, tool_names, cfg)

    assert _FETCH_ARTIFACT_TOOL in registry
    assert _FETCH_ARTIFACT_TOOL in tool_names

    # Store something in the artifact store
    store = cfg.artifact_store
    assert store is not None
    content = "the full artifact content"
    aid = store.store_artifact(content)

    # Call the fetch_artifact tool through the registry
    token = _active_artifact_store.set(store)
    try:
        results = await _execute_tools(
            [("tc1", "fetch_artifact", json.dumps({"artifact_id": aid}))],
            registry,
            config=cfg,
        )
    finally:
        _active_artifact_store.reset(token)

    _tc_id, output = results[0]
    parsed = json.loads(output)
    assert parsed["ok"] is True
    assert parsed["result"] == content


@pytest.mark.asyncio
async def test_fetch_artifact_tool_with_offset_and_length() -> None:
    """fetch_artifact supports offset and length for partial retrieval."""
    registry = ToolRegistry()
    tool_names: list[str] = []

    cfg = ToolExecutionConfig(artifact_projection=True)
    cfg = _setup_artifact_projection(registry, tool_names, cfg)

    store = cfg.artifact_store
    assert store is not None
    content = "abcdefghijklmnopqrstuvwxyz"
    aid = store.store_artifact(content)

    token = _active_artifact_store.set(store)
    try:
        results = await _execute_tools(
            [
                (
                    "tc1",
                    "fetch_artifact",
                    json.dumps({"artifact_id": aid, "offset": 5, "length": 10}),
                )
            ],
            registry,
            config=cfg,
        )
    finally:
        _active_artifact_store.reset(token)

    _tc_id, output = results[0]
    parsed = json.loads(output)
    assert parsed["ok"] is True
    assert parsed["result"] == "fghijklmno"


# ── 7. Setup is idempotent for registry ──────────────────────────────


def test_setup_idempotent() -> None:
    """Calling _setup_artifact_projection twice does not raise or
    duplicate the tool."""
    registry = ToolRegistry()
    names1: list[str] = []
    cfg1 = ToolExecutionConfig(artifact_projection=True)
    cfg1 = _setup_artifact_projection(registry, names1, cfg1)

    names2: list[str] = []
    cfg2 = ToolExecutionConfig(artifact_projection=True)
    cfg2 = _setup_artifact_projection(registry, names2, cfg2)

    assert _FETCH_ARTIFACT_TOOL in registry
    assert len(registry) == 1  # Only one tool registered


# ── 8. Disabled projection does not register tool ────────────────────


def test_disabled_does_not_register() -> None:
    """When artifact_projection is False, _setup_artifact_projection
    is a no-op."""
    registry = ToolRegistry()
    names: list[str] = []
    cfg = ToolExecutionConfig(artifact_projection=False)
    result_cfg = _setup_artifact_projection(registry, names, cfg)

    assert _FETCH_ARTIFACT_TOOL not in registry
    assert names == []
    assert result_cfg.artifact_store is None


# ── 9. Default config has projection disabled ────────────────────────


def test_default_config_disabled() -> None:
    """ToolExecutionConfig defaults to artifact_projection=False."""
    cfg = ToolExecutionConfig()
    assert cfg.artifact_projection is False
    assert cfg.artifact_projection_threshold == 4096
    assert cfg.artifact_store is None
