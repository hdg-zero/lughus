"""Policy-ready MCP adapter without coupling the core to a concrete SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from .tools import ConcurrencyMode, ToolEffect, ToolRisk


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None


class MCPClient(Protocol):
    async def list_tools(self) -> Sequence[MCPToolDescriptor]: ...
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    origin: str
    allowed_tools: frozenset[str]
    max_tools: int = 100
    max_output_characters: int = 100_000

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("MCP origin must be an HTTPS origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("MCP origin must not contain path, query or fragment")
        if self.max_tools <= 0 or self.max_output_characters <= 0:
            raise ValueError("MCP limits must be positive")


class MCPAdapter:
    """Expose only allowlisted remote tools; invocation still passes through local policy."""

    def __init__(self, client: MCPClient, config: MCPServerConfig) -> None:
        self.client, self.config = client, config
        self._snapshot: dict[str, MCPToolDescriptor] = {}

    async def refresh(self) -> tuple[MCPToolDescriptor, ...]:
        tools = tuple(await self.client.list_tools())
        if len(tools) > self.config.max_tools:
            raise ValueError("MCP server advertised too many tools")
        selected = tuple(tool for tool in tools if tool.name in self.config.allowed_tools)
        if len({tool.name for tool in selected}) != len(selected):
            raise ValueError("MCP server advertised duplicate tool names")
        self._snapshot = {tool.name: tool for tool in selected}
        return selected

    async def invoke(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if name not in self._snapshot:
            raise PermissionError("MCP tool is not present in the approved snapshot")
        result = await self.client.call_tool(name, arguments)
        if len(str(result)) > self.config.max_output_characters:
            raise ValueError("MCP tool result exceeds configured limit")
        return result

    @staticmethod
    def conservative_metadata() -> dict[str, Any]:
        return {
            "effects": frozenset({ToolEffect.EXTERNAL}),
            "risk": ToolRisk.UNKNOWN,
            "idempotent": False,
            "requires_approval": True,
            "concurrency": ConcurrencyMode.EXCLUSIVE,
        }
