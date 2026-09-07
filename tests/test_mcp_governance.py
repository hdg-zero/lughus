"""Tests for MCPAdapter governance: private invoke, schema fingerprint, pipeline integration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from lughus import ToolRegistry
from lughus.engine.tools import ToolDef
from lughus.interfaces.mcp import MCPAdapter, MCPServerConfig, MCPToolDescriptor

# ── Helpers ──────────────────────────────────────────────────────────────────


class FakeMCPClient:
    """Minimal MCPClient that returns configurable tool descriptors."""

    origin = "https://fake.example.com"

    def __init__(self, tools: Sequence[MCPToolDescriptor] | None = None) -> None:
        self._tools: list[MCPToolDescriptor] = list(tools or [])
        self.call_log: list[tuple[str, Mapping[str, Any]]] = []
        self.list_tools_count: int = 0

    async def list_tools(self) -> Sequence[MCPToolDescriptor]:
        self.list_tools_count += 1
        return self._tools

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self.call_log.append((name, arguments))
        return {"ok": True}


TOOL_A = MCPToolDescriptor(
    name="tool_a",
    description="Test tool A",
    input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
)


def _make_adapter(
    client: FakeMCPClient | None = None,
    tools: Sequence[MCPToolDescriptor] | None = None,
    cache_tools: bool = True,
) -> tuple[MCPAdapter, FakeMCPClient]:
    if client is None:
        client = FakeMCPClient(tools or [TOOL_A])
    config = MCPServerConfig(
        origin="https://fake.example.com",
        allowed_tools=frozenset(t.name for t in (tools or [TOOL_A])),
        cache_tools=cache_tools,
    )
    return MCPAdapter(client, config), client


# ── Test: invoke is no longer public ─────────────────────────────────────────


def test_invoke_is_private() -> None:
    """The old public `invoke` method must not exist; only `_invoke` is available."""
    adapter, _ = _make_adapter()
    assert not hasattr(adapter, "invoke"), "invoke should have been renamed to _invoke"
    assert hasattr(adapter, "_invoke"), "_invoke must exist"


# ── Test: registered tools go through the governance pipeline ────────────────


@pytest.mark.asyncio
async def test_registered_tools_use_governance_pipeline() -> None:
    """Tools registered via register_tools must carry conservative governance metadata.

    This verifies that the wrapper functions created by register_tools will
    route through the ToolRegistry (and thus ToolRuntime._execute_tools)
    rather than calling the MCP server directly.
    """
    adapter, client = _make_adapter()
    registry = ToolRegistry()
    registered = await adapter.register_tools(registry)

    assert "tool_a" in registered

    # Verify the registered ToolDef carries conservative metadata
    tool_def = registry.get_tool("tool_a")
    assert tool_def is not None
    assert tool_def.requires_approval is True
    assert tool_def.idempotent is False

    # Calling the registered function goes through _invoke (which calls client)
    fn = registry.get_fn("tool_a")
    assert fn is not None
    result = await fn(state={}, x=42)
    assert result == {"ok": True}
    assert client.call_log == [("tool_a", {"x": 42})]


# ── Test: schema fingerprint change raises ───────────────────────────────────


@pytest.mark.asyncio
async def test_remote_schema_drift_raises() -> None:
    """If the server's schemas change after refresh, _invoke must refuse."""
    tool_v1 = MCPToolDescriptor(
        name="tool_a",
        description="Test tool A",
        input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
    )
    tool_v2 = MCPToolDescriptor(
        name="tool_a",
        description="Test tool A",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    client = FakeMCPClient([tool_v1])
    adapter, _ = _make_adapter(client=client, tools=[tool_v1], cache_tools=False)
    await adapter.refresh()

    # Simulate server-side schema drift WITHOUT calling refresh().
    client._tools = [tool_v2]

    with pytest.raises(RuntimeError, match="MCP descriptors changed"):
        await adapter._invoke("tool_a", {"x": 1})


@pytest.mark.asyncio
async def test_fingerprint_stable_when_schemas_unchanged() -> None:
    """_invoke succeeds when schemas have not changed since refresh."""
    adapter, client = _make_adapter()
    await adapter.refresh()

    result = await adapter._invoke("tool_a", {"x": 1})
    assert result == {"ok": True}
    assert len(client.call_log) == 1


@pytest.mark.asyncio
async def test_refresh_resets_fingerprint() -> None:
    """After a second refresh (even with different schemas), _invoke succeeds."""
    tool_v1 = MCPToolDescriptor(
        name="tool_a",
        description="Test tool A",
        input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
    )
    tool_v2 = MCPToolDescriptor(
        name="tool_a",
        description="Test tool A",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    client = FakeMCPClient([tool_v1])
    adapter, _ = _make_adapter(client=client, tools=[tool_v1])
    await adapter.refresh()

    # Simulate server updating its schemas by changing the client's tools
    client._tools = [tool_v2]
    await adapter.refresh()  # Re-accept the new schemas

    # Should succeed because fingerprint was recomputed
    result = await adapter._invoke("tool_a", {"x": "hello"})
    assert result == {"ok": True}


def test_mcp_client_cannot_hide_a_different_origin() -> None:
    client = FakeMCPClient()
    client.origin = "https://other.example"
    with pytest.raises(ValueError, match="origin"):
        MCPAdapter(client, MCPServerConfig("https://fake.example.com", frozenset()))


@pytest.mark.asyncio
async def test_smart_cache_avoids_list_tools_on_invoke() -> None:
    """Default cache_tools=True avoids list_tools on every invoke unless invalidated."""
    adapter, client = _make_adapter(cache_tools=True)
    await adapter.refresh()
    assert client.list_tools_count == 1

    # First invoke uses cache
    res1 = await adapter._invoke("tool_a", {"x": 1})
    assert res1 == {"ok": True}
    assert client.list_tools_count == 1

    # Invalidate cache -> next invoke triggers refresh
    adapter.invalidate()
    res2 = await adapter._invoke("tool_a", {"x": 2})
    assert res2 == {"ok": True}
    assert client.list_tools_count == 2


@pytest.mark.asyncio
async def test_as_tools_converts_to_tool_defs() -> None:
    """as_tools converts approved MCP descriptors into ToolDef objects without state."""
    adapter, client = _make_adapter()
    tools = await adapter.as_tools()
    assert len(tools) == 1
    tool_def = tools[0]
    assert isinstance(tool_def, ToolDef)
    assert tool_def.name == "tool_a"
    assert tool_def.takes_state is False
    assert tool_def.requires_approval is True

    # Calling tool_def executes remote tool
    res = await tool_def(x=99)
    assert res == {"ok": True}
    assert client.call_log == [("tool_a", {"x": 99})]
