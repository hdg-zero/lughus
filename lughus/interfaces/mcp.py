"""Policy-ready MCP adapter, native stdio/SSE transports, and ToolDef bridge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from ..core.domain import canonical_hash
from ..engine.tools import ConcurrencyMode, ToolDef, ToolEffect, ToolRisk

__all__ = [
    "MCPAdapter",
    "MCPClient",
    "MCPServerConfig",
    "MCPToolDescriptor",
    "SSEMCPClient",
    "StdioMCPClient",
]

_logger = logging.getLogger(__name__)


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
    cache_tools: bool = True

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if parsed.scheme not in {"https", "http", "stdio"}:
            raise ValueError("MCP origin must be an HTTPS, HTTP, or stdio origin")
        if parsed.scheme in {"https", "http"}:
            if not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("MCP origin must be an HTTPS or HTTP origin without credentials")
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("MCP origin must not contain path, query or fragment")
        if self.max_tools <= 0 or self.max_output_characters <= 0:
            raise ValueError("MCP limits must be positive")


class StdioMCPClient:
    """Native MCP client communicating with a local subprocess over stdio via JSON-RPC 2.0."""

    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        origin: str | None = None,
        on_tools_changed: Callable[[], None] | None = None,
    ) -> None:
        if isinstance(command, str):
            self.command = tuple(shlex.split(command))
        else:
            self.command = tuple(command)

        if not self.command:
            raise ValueError("Command must not be empty")

        cmd_name = Path(self.command[0]).name
        self.origin = origin or f"stdio://local/{cmd_name}"
        self.cwd = str(cwd) if cwd else None
        self.env = env
        self.on_tools_changed = on_tools_changed

        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._request_id = 0
        self._initialized = False
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> None:
        async with self._lock:
            if self._process is None or self._process.returncode is not None:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    env=dict(self.env) if self.env else None,
                )
                self._reader_task = asyncio.create_task(self._read_loop())
                self._initialized = False

            if not self._initialized:
                await self._send_request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "lughus", "version": "0.18.0"},
                    },
                )
                await self._send_notification("notifications/initialized", {})
                self._initialized = True

    async def _read_loop(self) -> None:
        try:
            while self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8").strip()
                if not text:
                    continue
                try:
                    msg = json.loads(text)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                if "id" in msg and msg["id"] in self._pending:
                    fut = self._pending.pop(msg["id"])
                    if not fut.done():
                        if msg.get("error"):
                            err = msg["error"]
                            msg_str = (
                                err.get("message", "MCP error")
                                if isinstance(err, dict)
                                else str(err)
                            )
                            fut.set_exception(RuntimeError(f"MCP error: {msg_str}"))
                        else:
                            fut.set_result(msg.get("result"))
                elif (
                    msg.get("method") == "notifications/tools/list_changed"
                    and self.on_tools_changed
                ):
                    self.on_tools_changed()
        except asyncio.CancelledError:
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("MCP stdio connection closed"))
            self._pending.clear()

    async def _send_request(self, method: str, params: Mapping[str, Any]) -> Any:
        if self._process is None or self._process.stdin is None:
            raise ConnectionError("StdioMCPClient is not connected")

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._request_id += 1
        req_id = self._request_id
        self._pending[req_id] = fut

        payload = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        self._process.stdin.write(payload.encode("utf-8"))
        await self._process.stdin.drain()
        return await fut

    async def _send_notification(self, method: str, params: Mapping[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ConnectionError("StdioMCPClient is not connected")
        payload = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                }
            )
            + "\n"
        )
        self._process.stdin.write(payload.encode("utf-8"))
        await self._process.stdin.drain()

    async def list_tools(self) -> Sequence[MCPToolDescriptor]:
        await self._ensure_connected()
        res = await self._send_request("tools/list", {})
        tools_data = res.get("tools", []) if isinstance(res, dict) else []
        descriptors: list[MCPToolDescriptor] = []
        for t in tools_data:
            descriptors.append(
                MCPToolDescriptor(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    output_schema=t.get("outputSchema"),
                )
            )
        return tuple(descriptors)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        await self._ensure_connected()
        res = await self._send_request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(res, dict) and "content" in res:
            content = res["content"]
            if isinstance(content, list):
                text_items = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if text_items:
                    return "\n".join(text_items)
            return content
        return res

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._process:
            if self._process.stdin:
                with contextlib.suppress(OSError):
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except (OSError, TimeoutError):
                with contextlib.suppress(OSError):
                    self._process.kill()
            self._process = None

    async def __aenter__(self) -> StdioMCPClient:
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class SSEMCPClient:
    """Native MCP client communicating with a remote server via SSE and HTTP POST."""

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str] | None = None,
        origin: str | None = None,
        timeout: float = 30.0,
        on_tools_changed: Callable[[], None] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        parsed = urlsplit(endpoint)
        self.origin = origin or f"{parsed.scheme}://{parsed.netloc}"
        self.headers = dict(headers or {})
        self.timeout = timeout
        self.on_tools_changed = on_tools_changed

        self._custom_client = client
        self._client: httpx.AsyncClient | None = None
        self._post_url: str = endpoint
        self._endpoint_ready = asyncio.Event()
        self._request_id = 0
        self._initialized = False
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._sse_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> None:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                self._endpoint_ready = asyncio.Event()
                if self._custom_client is not None and not self._custom_client.is_closed:
                    self._client = self._custom_client
                else:
                    self._client = httpx.AsyncClient(headers=self.headers, timeout=self.timeout)
                self._sse_task = asyncio.create_task(self._sse_listener())
                self._initialized = False

            if not self._initialized:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._endpoint_ready.wait(), timeout=min(self.timeout, 5.0)
                    )

                await self._send_request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "lughus", "version": "0.18.0"},
                    },
                )
                await self._send_notification("notifications/initialized", {})
                self._initialized = True

    async def _sse_listener(self) -> None:
        if self._client is None:
            return
        sse_headers = {"Accept": "text/event-stream", **self.headers}
        try:
            async with self._client.stream("GET", self.endpoint, headers=sse_headers) as response:
                current_event = "message"
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        data_str = line.split(":", 1)[1].strip()
                        if current_event == "endpoint":
                            self._post_url = urljoin(self.endpoint, data_str)
                            self._endpoint_ready.set()
                        elif current_event == "message":
                            try:
                                msg = json.loads(data_str)
                                if "id" in msg and msg["id"] in self._pending:
                                    fut = self._pending.pop(msg["id"])
                                    if not fut.done():
                                        if msg.get("error"):
                                            fut.set_exception(
                                                RuntimeError(f"MCP error: {msg['error']}")
                                            )
                                        else:
                                            fut.set_result(msg.get("result"))
                                elif (
                                    msg.get("method") == "notifications/tools/list_changed"
                                    and self.on_tools_changed
                                ):
                                    self.on_tools_changed()
                            except (json.JSONDecodeError, KeyError, ValueError):
                                pass
        except asyncio.CancelledError:
            pass
        except (httpx.HTTPError, OSError):
            pass

    async def _send_request(self, method: str, params: Mapping[str, Any]) -> Any:
        if self._client is None:
            raise ConnectionError("SSEMCPClient is not connected")

        self._request_id += 1
        req_id = self._request_id
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        resp = await self._client.post(self._post_url, json=payload)
        resp.raise_for_status()

        if resp.content:
            try:
                data = resp.json()
                if data.get("error"):
                    err = data["error"]
                    msg = err.get("message", "MCP error") if isinstance(err, dict) else str(err)
                    raise RuntimeError(f"MCP error: {msg}")
                if "result" in data:
                    return data["result"]
            except ValueError:
                pass

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = fut
        return await fut

    async def _send_notification(self, method: str, params: Mapping[str, Any]) -> None:
        if self._client is None:
            raise ConnectionError("SSEMCPClient is not connected")
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._client.post(self._post_url, json=payload)

    async def list_tools(self) -> Sequence[MCPToolDescriptor]:
        await self._ensure_connected()
        res = await self._send_request("tools/list", {})
        tools_data = res.get("tools", []) if isinstance(res, dict) else []
        descriptors: list[MCPToolDescriptor] = []
        for t in tools_data:
            descriptors.append(
                MCPToolDescriptor(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    output_schema=t.get("outputSchema"),
                )
            )
        return tuple(descriptors)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        await self._ensure_connected()
        res = await self._send_request("tools/call", {"name": name, "arguments": arguments})
        if isinstance(res, dict) and "content" in res:
            content = res["content"]
            if isinstance(content, list):
                text_items = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if text_items:
                    return "\n".join(text_items)
            return content
        return res

    async def close(self) -> None:
        if self._sse_task:
            self._sse_task.cancel()
            self._sse_task = None
        if self._client:
            if self._custom_client is None:
                await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> SSEMCPClient:
        await self._ensure_connected()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()


class MCPAdapter:
    """Expose only allowlisted remote tools; invocation still passes through local policy."""

    def __init__(self, client: MCPClient, config: MCPServerConfig) -> None:
        self.client, self.config = client, config
        if client.origin.rstrip("/") != config.origin.rstrip("/"):
            raise ValueError("MCP client origin does not match the validated configuration")
        self._snapshot: dict[str, MCPToolDescriptor] = {}
        self._schema_fingerprint: str | None = None
        self._cache_valid: bool = False

        if hasattr(client, "on_tools_changed") and client.on_tools_changed is None:
            client.on_tools_changed = self.invalidate

    def invalidate(self) -> None:
        """Invalidate the cached tools snapshot."""
        self._cache_valid = False

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
        return canonical_hash(schemas)

    async def refresh(self) -> tuple[MCPToolDescriptor, ...]:
        tools = tuple(await self.client.list_tools())
        if len(tools) > self.config.max_tools:
            raise ValueError("MCP server advertised too many tools")
        selected = tuple(tool for tool in tools if tool.name in self.config.allowed_tools)
        if len({tool.name for tool in selected}) != len(selected):
            raise ValueError("MCP server advertised duplicate tool names")
        self._snapshot = {tool.name: tool for tool in selected}
        self._schema_fingerprint = self._compute_fingerprint(self._snapshot)
        self._cache_valid = True
        return selected

    async def _invoke(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if not self._cache_valid or not self._snapshot:
            await self.refresh()

        if name not in self._snapshot:
            raise PermissionError("MCP tool is not present in the approved snapshot")

        if not self.config.cache_tools:
            # When caching is disabled, re-query server to detect schema drift
            remote = {t.name: t for t in await self.client.list_tools()}
            if len(remote) > self.config.max_tools:
                raise ValueError("MCP server advertised too many tools")
            remote_selected = {
                n: d
                for n, d in remote.items()
                if n in self.config.allowed_tools and n in self._snapshot
            }
            current_fingerprint = self._compute_fingerprint(remote_selected)
            if current_fingerprint != self._schema_fingerprint:
                raise RuntimeError(
                    "MCP tool schemas changed on the server since last refresh; "
                    "call refresh() to re-approve before invoking"
                )

        result = await self.client.call_tool(name, arguments)
        if len(str(result)) > self.config.max_output_characters:
            raise ValueError("MCP tool result exceeds configured limit")
        return result

    def descriptor_to_tool_def(
        self,
        descriptor: MCPToolDescriptor,
        *,
        effects: frozenset[ToolEffect] | None = None,
        risk: ToolRisk = ToolRisk.UNKNOWN,
        requires_approval: bool = True,
        concurrency: ConcurrencyMode = ConcurrencyMode.SERIAL_PER_TOOL,
        idempotent: bool = False,
        required_scopes: frozenset[str] | None = None,
        timeout: float | None = None,
        **_kwargs: Any,
    ) -> ToolDef:
        """Convert an MCPToolDescriptor to a Lughus ToolDef."""
        target_name = descriptor.name

        async def remote_tool_fn(**kwargs: Any) -> Any:
            call_kwargs = {k: v for k, v in kwargs.items() if k != "state"}
            return await self._invoke(target_name, call_kwargs)

        input_schema = dict(descriptor.input_schema)
        output_schema = (
            dict(descriptor.output_schema) if descriptor.output_schema is not None else None
        )
        validator = Draft202012Validator(input_schema)
        output_validator = Draft202012Validator(output_schema) if output_schema else None

        return ToolDef(
            name=descriptor.name,
            description=descriptor.description,
            fn=remote_tool_fn,
            parameters_schema=input_schema,
            validator=validator,
            output_schema=output_schema,
            output_validator=output_validator,
            effects=effects or frozenset({ToolEffect.EXTERNAL}),
            risk=risk,
            requires_approval=requires_approval,
            concurrency=concurrency,
            idempotent=idempotent,
            required_scopes=required_scopes or frozenset(),
            takes_state=False,
            timeout=timeout,
        )

    async def as_tools(self, **overrides: Any) -> tuple[ToolDef, ...]:
        """Return the approved snapshot converted to ToolDef instances."""
        if not self._snapshot or not self._cache_valid:
            await self.refresh()
        metadata = self.conservative_metadata()
        metadata.update(overrides)
        return tuple(
            self.descriptor_to_tool_def(descriptor, **metadata)
            for descriptor in self._snapshot.values()
        )

    async def register_tools(self, registry: Any, **overrides: Any) -> tuple[str, ...]:
        """Register the approved snapshot so calls use the normal ToolRuntime pipeline."""
        tools = await self.as_tools(**overrides)
        registered: list[str] = []
        for td in tools:
            if hasattr(registry, "register"):
                registry.register(td)
            else:
                registry.tool(
                    td.name,
                    td.description,
                    td.parameters_schema,
                    output_schema=td.output_schema,
                    effects=td.effects,
                    risk=td.risk,
                    requires_approval=td.requires_approval,
                    concurrency=td.concurrency,
                )(td.fn)
            registered.append(td.name)
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
