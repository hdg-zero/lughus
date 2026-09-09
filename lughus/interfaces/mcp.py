"""Policy-ready MCP adapter, native stdio/SSE transports, and ToolDef bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from ..core.domain import canonical_hash
from ..core.errors import SafeToolError
from ..engine.tools import ConcurrencyMode, ToolDef, ToolEffect, ToolRisk
from ..infra.http import read_json, same_origin_url, sse_events

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


class _RPCClient:
    """Shared bounded correlation, pagination and MCP result semantics."""

    timeout: float
    max_response_bytes: int
    on_tools_changed: Callable[[], None] | None

    def _init_rpc(self) -> None:
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._request_id = 0
        self._failure: Exception | None = None
        self._closed = False
        self._initialized = False
        self._lock = asyncio.Lock()

    def _accept(self, message: Any) -> None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid MCP JSON-RPC response")
        request_id = message.get("id")
        if isinstance(request_id, int) and request_id in self._pending:
            future = self._pending[request_id]
            if not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError("MCP protocol request failed"))
                elif "result" in message:
                    future.set_result(message["result"])
                else:
                    future.set_exception(ValueError("Missing MCP result"))
        elif message.get("method") == "notifications/tools/list_changed":
            if self.on_tools_changed is not None:
                self.on_tools_changed()

    def _fail(self, exc: Exception) -> None:
        self._failure = exc
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)

    async def _write(self, payload: Mapping[str, Any]) -> None:
        raise NotImplementedError

    async def _ensure_connected(self) -> None:
        raise NotImplementedError

    async def _send_request(self, method: str, params: Mapping[str, Any]) -> Any:
        if self._closed or self._failure is not None:
            raise ConnectionError("MCP transport is closed or failed") from self._failure
        if len(self._pending) >= 128:
            raise RuntimeError("Too many outstanding MCP requests")
        self._request_id += 1
        request_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future  # before POST/write: SSE may answer immediately
        try:
            async with asyncio.timeout(self.timeout):
                await self._write(
                    {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
                )
                return await future
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # observe a concurrent disconnect if writing failed

    async def _initialize(self) -> None:
        result = await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "lughus", "version": "0.21.0"},
            },
        )
        if not isinstance(result, dict) or result.get("protocolVersion") != "2024-11-05":
            raise ValueError("Unsupported MCP protocol version")
        await self._write({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._initialized = True

    async def list_tools(self) -> Sequence[MCPToolDescriptor]:
        async with asyncio.timeout(self.timeout):
            await self._ensure_connected()
            result: list[MCPToolDescriptor] = []
            cursor: str | None = None
            seen: set[str] = set()
            for _ in range(100):
                page = await self._send_request("tools/list", {"cursor": cursor} if cursor else {})
                if not isinstance(page, dict) or not isinstance(page.get("tools"), list):
                    raise ValueError("Invalid MCP tools page")
                for tool in page["tools"]:
                    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                        raise ValueError("Invalid MCP tool descriptor")
                    result.append(
                        MCPToolDescriptor(
                            tool["name"],
                            tool.get("description", ""),
                            tool.get("inputSchema", {}),
                            tool.get("outputSchema"),
                        )
                    )
                    if len(result) > 10_000:
                        raise ValueError("MCP discovery exceeds limit")
                cursor = page.get("nextCursor")
                if cursor is None:
                    return tuple(result)
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise ValueError("Invalid or cyclic MCP pagination")
                seen.add(cursor)
            raise ValueError("MCP pagination exceeds limit")

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        async with asyncio.timeout(self.timeout):
            await self._ensure_connected()
            result = await self._send_request(
                "tools/call", {"name": name, "arguments": dict(arguments)}
            )
        if not isinstance(result, dict):
            raise ValueError("Invalid MCP tool result")
        if result.get("isError") is True:
            raise SafeToolError("mcp_tool_error", "Remote MCP tool reported failure")
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content", [])
        if (
            isinstance(content, list)
            and content
            and all(isinstance(item, dict) and item.get("type") == "text" for item in content)
        ):
            return "\n".join(str(item.get("text", "")) for item in content)
        return content  # preserve multimodal blocks instead of silently dropping them

    async def close(self) -> None:
        self._closed = True
        self._fail(ConnectionError("MCP client closed"))

    async def __aenter__(self) -> _RPCClient:
        try:
            await self._ensure_connected()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()


class StdioMCPClient(_RPCClient):
    """Local trusted executable. This transport is not a sandbox."""

    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        origin: str | None = None,
        on_tools_changed: Callable[[], None] | None = None,
        timeout: float = 30.0,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        self.command = tuple(shlex.split(command) if isinstance(command, str) else command)
        if not self.command or timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("Command and positive transport limits are required")
        self.origin = origin or f"stdio://local/{Path(self.command[0]).name}"
        self.cwd = str(cwd) if cwd is not None else None
        # Do not implicitly give a third-party subprocess the application's secrets.
        self.env = dict(env) if env is not None else {"PATH": os.defpath}
        self.timeout, self.max_response_bytes = timeout, max_response_bytes
        self.on_tools_changed = on_tools_changed
        self._process: asyncio.subprocess.Process | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._write_lock = asyncio.Lock()
        self._init_rpc()

    async def _ensure_connected(self) -> None:
        async with asyncio.timeout(self.timeout), self._lock:
            if self._closed or self._failure is not None:
                raise ConnectionError("MCP transport unavailable") from self._failure
            if self._process is None:
                self._process = await asyncio.create_subprocess_exec(
                    *self.command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self.cwd,
                    env=self.env,
                    limit=self.max_response_bytes,
                )
                self._tasks = [
                    asyncio.create_task(self._read_loop()),
                    asyncio.create_task(self._drain_stderr()),
                ]
            if not self._initialized:
                await self._initialize()

    async def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while line := await self._process.stdout.readline():
                if len(line) > self.max_response_bytes:
                    raise ValueError("MCP response exceeds size limit")
                self._accept(json.loads(line))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
        finally:
            self._fail(self._failure or ConnectionError("MCP stdout closed"))

    async def _drain_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while await self._process.stderr.read(8192):
            pass  # drain without retaining unbounded diagnostics or logging secrets

    async def _write(self, payload: Mapping[str, Any]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ConnectionError("MCP process unavailable")
        data = (json.dumps(payload) + "\n").encode()
        if len(data) > self.max_response_bytes:
            raise ValueError("MCP request exceeds size limit")
        async with self._write_lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()

    async def close(self) -> None:
        await super().close()
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), 2.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


class SSEMCPClient(_RPCClient):
    """MCP 2024-11-05 HTTP+SSE transport with origin pinning and bounded RPCs.

    No silent reconnection or replay of possibly-effectful requests. Construct a
    new client after a failed session. HTTP redirects are always rejected.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str] | None = None,
        origin: str | None = None,
        timeout: float = 30.0,
        on_tools_changed: Callable[[], None] | None = None,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = 2_000_000,
    ) -> None:
        from ..infra.http import origin as parse_origin

        scheme, host, _ = parse_origin(endpoint)
        if scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Cleartext MCP requires a loopback endpoint")
        if timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("Transport limits must be positive")
        parsed = urlsplit(endpoint)
        self.origin = origin or f"{parsed.scheme}://{parsed.netloc}"
        if parse_origin(self.origin) != parse_origin(endpoint):
            raise ValueError("Origin does not match endpoint")
        self.endpoint, self.timeout = endpoint, timeout
        self.max_response_bytes = max_response_bytes
        self.headers = dict(headers or {})
        self.on_tools_changed = on_tools_changed
        self._owned = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        )
        self._post_url: str | None = None
        self._ready = asyncio.Event()
        self._sse_task: asyncio.Task[None] | None = None
        self._init_rpc()

    async def _ensure_connected(self) -> None:
        async with asyncio.timeout(self.timeout), self._lock:
            if self._closed or self._failure is not None:
                raise ConnectionError("MCP session unavailable") from self._failure
            if self._sse_task is None:
                self._sse_task = asyncio.create_task(self._listen())
            await self._ready.wait()
            if self._failure is not None:
                raise ConnectionError("MCP SSE initialization failed") from self._failure
            if not self._initialized:
                await self._initialize()

    async def _listen(self) -> None:
        try:
            async with self._client.stream(
                "GET",
                self.endpoint,
                headers={**self.headers, "Accept": "text/event-stream"},
                follow_redirects=False,
            ) as response:
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise ValueError("Expected MCP SSE content type")
                async for kind, data in sse_events(response, self.max_response_bytes):
                    if kind == "endpoint":
                        url = same_origin_url(self.endpoint, data)
                        if self._post_url is not None and url != self._post_url:
                            raise ValueError("MCP endpoint changed during a session")
                        self._post_url = url
                        self._ready.set()
                    elif kind == "message":
                        self._accept(json.loads(data))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._fail(exc)
        finally:
            self._fail(self._failure or ConnectionError("MCP SSE connection closed"))
            self._ready.set()

    async def _write(self, payload: Mapping[str, Any]) -> None:
        if self._post_url is None:
            raise ConnectionError("MCP POST endpoint not established")
        async with self._client.stream(
            "POST",
            self._post_url,
            json=dict(payload),
            headers=self.headers,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            if response.status_code not in {
                202,
                204,
            } and "application/json" in response.headers.get("content-type", ""):
                self._accept(await read_json(response, self.max_response_bytes))

    async def close(self) -> None:
        await super().close()
        if self._sse_task is not None:
            self._sse_task.cancel()
            await asyncio.gather(self._sse_task, return_exceptions=True)
            self._sse_task = None
        if self._owned:
            await self._client.aclose()


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
                "description": desc.description,
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

    async def _invoke(
        self, name: str, arguments: Mapping[str, Any], *, expected_fingerprint: str | None = None
    ) -> Any:
        if not self._snapshot:
            raise PermissionError("Call refresh() to approve MCP descriptors before use")
        if not self._cache_valid or not self.config.cache_tools:
            remote = tuple(await self.client.list_tools())
            if len(remote) > self.config.max_tools:
                raise ValueError("MCP server advertised too many tools")
            selected = {
                tool.name: tool for tool in remote if tool.name in self.config.allowed_tools
            }
            if len(selected) != sum(tool.name in self.config.allowed_tools for tool in remote):
                raise ValueError("MCP server advertised duplicate tools")
            if self._compute_fingerprint(selected) != self._schema_fingerprint:
                raise RuntimeError(
                    "MCP descriptors changed; explicitly refresh and rebuild registry"
                )
            self._cache_valid = True

        if expected_fingerprint is not None and expected_fingerprint != self._schema_fingerprint:
            raise RuntimeError("Registered MCP tool belongs to an obsolete descriptor snapshot")
        if name not in self._snapshot:
            raise PermissionError("MCP tool is not present in the approved snapshot")

        Draft202012Validator(dict(self._snapshot[name].input_schema)).validate(dict(arguments))
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
        fingerprint = self._schema_fingerprint

        async def remote_tool_fn(**kwargs: Any) -> Any:
            call_kwargs = {k: v for k, v in kwargs.items() if k != "state"}
            return await self._invoke(target_name, call_kwargs, expected_fingerprint=fingerprint)

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
