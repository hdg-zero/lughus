"""Policy-ready MCP adapter without coupling the core to a concrete SDK."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from ..engine.tools import ConcurrencyMode, ToolEffect, ToolRisk


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    name: str
    description: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None


class MCPClient(Protocol):
    origin: str

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
        if client.origin.rstrip("/") != config.origin.rstrip("/"):
            raise ValueError("MCP client origin does not match the validated configuration")
        self._snapshot: dict[str, MCPToolDescriptor] = {}
        self._schema_fingerprint: str | None = None

    @staticmethod
    def _compute_fingerprint(snapshot: Mapping[str, MCPToolDescriptor]) -> str:
        """Compute a SHA-256 fingerprint of all tool schemas in the snapshot."""
        schemas = {
            name: {
                "input_schema": dict(desc.input_schema),
                "output_schema": dict(desc.output_schema) if desc.output_schema else None,
            }
            for name, desc in sorted(snapshot.items())
        }
        canonical = json.dumps(schemas, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def refresh(self) -> tuple[MCPToolDescriptor, ...]:
        tools = tuple(await self.client.list_tools())
        if len(tools) > self.config.max_tools:
            raise ValueError("MCP server advertised too many tools")
        selected = tuple(tool for tool in tools if tool.name in self.config.allowed_tools)
        if len({tool.name for tool in selected}) != len(selected):
            raise ValueError("MCP server advertised duplicate tool names")
        self._snapshot = {tool.name: tool for tool in selected}
        self._schema_fingerprint = self._compute_fingerprint(self._snapshot)
        return selected

    async def _invoke(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if name not in self._snapshot:
            raise PermissionError("MCP tool is not present in the approved snapshot")
        current_fingerprint = self._compute_fingerprint(self._snapshot)
        if current_fingerprint != self._schema_fingerprint:
            raise RuntimeError(
                "MCP tool schema fingerprint changed since last refresh; "
                "refusing to execute against an unvalidated schema"
            )
        result = await self.client.call_tool(name, arguments)
        if len(str(result)) > self.config.max_output_characters:
            raise ValueError("MCP tool result exceeds configured limit")
        return result

    async def register_tools(self, registry: Any) -> tuple[str, ...]:
        """Register the approved snapshot so calls use the normal ToolRuntime pipeline."""
        if not self._snapshot:
            await self.refresh()
        registered: list[str] = []
        metadata = self.conservative_metadata()
        for descriptor in self._snapshot.values():

            def build_remote_tool(target_name: str) -> Any:
                async def remote_tool_fn(*, state: dict, **kwargs: Any) -> Any:
                    del state
                    return await self._invoke(target_name, kwargs)

                return remote_tool_fn

            tool_fn = build_remote_tool(descriptor.name)
            registry.tool(
                descriptor.name,
                descriptor.description,
                dict(descriptor.input_schema),
                output_schema=(
                    dict(descriptor.output_schema) if descriptor.output_schema is not None else None
                ),
                **metadata,
            )(tool_fn)
            registered.append(descriptor.name)
        return tuple(registered)

    @staticmethod
    def conservative_metadata() -> dict[str, Any]:
        return {
            "effects": frozenset({ToolEffect.EXTERNAL}),
            "risk": ToolRisk.UNKNOWN,
            "idempotent": False,
            "requires_approval": True,
            "concurrency": ConcurrencyMode.SERIAL_PER_TOOL,
        }
