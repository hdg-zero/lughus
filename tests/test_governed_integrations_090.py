import pytest

from lughus.interfaces.mcp import MCPAdapter, MCPServerConfig, MCPToolDescriptor
from lughus.tools import ToolRegistry, ToolRisk


class _MCP:
    origin = "https://mcp.example"

    async def list_tools(self):
        return [MCPToolDescriptor("search", "Search", {"type": "object", "properties": {}})]

    async def call_tool(self, name, arguments):
        return {"ok": True}


@pytest.mark.asyncio
async def test_mcp_tools_are_registered_with_conservative_policy_metadata():
    registry = ToolRegistry()
    adapter = MCPAdapter(_MCP(), MCPServerConfig("https://mcp.example", frozenset({"search"})))
    assert await adapter.register_tools(registry) == ("search",)
    tool = registry.get_tool("search")
    assert tool.risk == ToolRisk.UNKNOWN and tool.requires_approval


def test_mcp_client_cannot_hide_a_different_origin():
    client = _MCP()
    client.origin = "https://other.example"
    with pytest.raises(ValueError, match="origin"):
        MCPAdapter(client, MCPServerConfig("https://mcp.example", frozenset()))
