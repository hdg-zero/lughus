"""Tests for native MCP transports: StdioMCPClient and SSEMCPClient."""

from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from lughus.interfaces.mcp import (
    MCPServerConfig,
    SSEMCPClient,
    StdioMCPClient,
)


def test_mcp_server_config_origins() -> None:
    # Valid schemes
    cfg1 = MCPServerConfig("https://example.com", allowed_tools=frozenset(["echo"]))
    assert cfg1.origin == "https://example.com"
    assert cfg1.cache_tools is True

    cfg2 = MCPServerConfig("http://localhost:8000", allowed_tools=frozenset(["echo"]))
    assert cfg2.origin == "http://localhost:8000"

    cfg3 = MCPServerConfig("stdio://local/my-tool", allowed_tools=frozenset(["echo"]))
    assert cfg3.origin == "stdio://local/my-tool"

    # Invalid schemes
    with pytest.raises(ValueError, match="MCP origin must be an HTTPS, HTTP, or stdio origin"):
        MCPServerConfig("ftp://example.com", allowed_tools=frozenset())

    with pytest.raises(ValueError, match="MCP origin must not contain path, query or fragment"):
        MCPServerConfig("https://example.com?query=1", allowed_tools=frozenset())


def test_stdio_mcp_client_empty_command_raises() -> None:
    with pytest.raises(ValueError, match="Command must not be empty"):
        StdioMCPClient("")
    with pytest.raises(ValueError, match="Command must not be empty"):
        StdioMCPClient([])


@pytest.mark.asyncio
async def test_stdio_mcp_client_e2e() -> None:
    server_script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line: continue\n"
        "    req = json.loads(line)\n"
        "    method = req.get('method')\n"
        "    req_id = req.get('id')\n"
        "    if method == 'initialize':\n"
        "        res = {'jsonrpc': '2.0', 'id': req_id,\n"
        "               'result': {'protocolVersion': '2024-11-05'}}\n"
        "        sys.stdout.write(json.dumps(res) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif method == 'notifications/initialized':\n"
        "        pass\n"
        "    elif method == 'tools/list':\n"
        "        tool_data = {'name': 'calc', 'description': 'Calculator',\n"
        "                     'inputSchema': {'type': 'object', 'properties': "
        "{'a': {'type': 'integer'}, 'b': {'type': 'integer'}}}}\n"
        "        res = {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': [tool_data]}}\n"
        "        sys.stdout.write(json.dumps(res) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif method == 'tools/call':\n"
        "        args = req.get('params', {}).get('arguments', {})\n"
        "        val = args.get('a', 0) + args.get('b', 0)\n"
        "        res = {'jsonrpc': '2.0', 'id': req_id,\n"
        "               'result': {'content': [{'type': 'text', 'text': f'result: {val}'}]}}\n"
        "        sys.stdout.write(json.dumps(res) + '\\n')\n"
        "        sys.stdout.flush()\n"
    )

    client = StdioMCPClient([sys.executable, "-u", "-c", server_script])
    async with client:
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "calc"
        assert tools[0].description == "Calculator"

        result = await client.call_tool("calc", {"a": 10, "b": 32})
        assert result == "result: 42"


@pytest.mark.asyncio
async def test_stdio_mcp_client_tools_changed_notification() -> None:
    server_script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    line = line.strip()\n"
        "    if not line: continue\n"
        "    req = json.loads(line)\n"
        "    method = req.get('method')\n"
        "    req_id = req.get('id')\n"
        "    if method == 'initialize':\n"
        "        res = {'jsonrpc': '2.0', 'id': req_id,\n"
        "               'result': {'protocolVersion': '2024-11-05'}}\n"
        "        sys.stdout.write(json.dumps(res) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif method == 'notifications/initialized':\n"
        "        notif = {'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'}\n"
        "        sys.stdout.write(json.dumps(notif) + '\\n')\n"
        "        sys.stdout.flush()\n"
        "    elif method == 'tools/list':\n"
        "        res = {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': []}}\n"
        "        sys.stdout.write(json.dumps(res) + '\\n')\n"
        "        sys.stdout.flush()\n"
    )

    changed_event = asyncio.Event()

    def on_change() -> None:
        changed_event.set()

    client = StdioMCPClient([sys.executable, "-u", "-c", server_script], on_tools_changed=on_change)
    async with client:
        await client.list_tools()
        await asyncio.wait_for(changed_event.wait(), timeout=3.0)
        assert changed_event.is_set()


@pytest.mark.asyncio
async def test_sse_mcp_client_e2e() -> None:
    endpoint = "https://mcp.example.com/sse"
    post_endpoint = "https://mcp.example.com/rpc"

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and str(request.url) == endpoint:
            sse_content = f"event: endpoint\ndata: {post_endpoint}\n\n".encode()
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=sse_content,
            )
        if request.method == "POST" and str(request.url) == post_endpoint:
            payload = json.loads(request.content.decode())
            req_id = payload.get("id")
            method = payload.get("method")
            if method == "initialize":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"protocolVersion": "2024-11-05"},
                    },
                )
            if method == "notifications/initialized":
                return httpx.Response(204)
            if method == "tools/list":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": [
                                {
                                    "name": "greet",
                                    "description": "Greeting tool",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"name": {"type": "string"}},
                                    },
                                }
                            ]
                        },
                    },
                )
            if method == "tools/call":
                name = payload.get("params", {}).get("arguments", {}).get("name", "world")
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"content": [{"type": "text", "text": f"Hello {name}!"}]},
                    },
                )
            return httpx.Response(404)

        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    client = SSEMCPClient(endpoint, client=http_client)
    async with client:
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "greet"
        assert tools[0].description == "Greeting tool"

        res = await client.call_tool("greet", {"name": "Alice"})
        assert res == "Hello Alice!"


@pytest.mark.asyncio
async def test_sse_mcp_client_error_handling() -> None:
    endpoint = "https://mcp.example.com/sse"

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"event: endpoint\ndata: /rpc\n\n",
            )
        if request.method == "POST":
            payload = json.loads(request.content.decode())
            req_id = payload.get("id")
            method = payload.get("method")
            if method == "initialize":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": {}})
            if method == "notifications/initialized":
                return httpx.Response(204)
            if method == "tools/call":
                return httpx.Response(
                    200,
                    json={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32603, "message": "Internal tool failure"},
                    },
                )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": {}})
        return httpx.Response(404)

    transport = httpx.MockTransport(mock_handler)
    http_client = httpx.AsyncClient(transport=transport)

    client = SSEMCPClient(endpoint, client=http_client)
    async with client:
        with pytest.raises(RuntimeError, match="Internal tool failure"):
            await client.call_tool("bad_tool", {})
