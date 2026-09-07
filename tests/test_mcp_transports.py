"""Bounded MCP correlation, errors and real stdio smoke test."""

import asyncio
import sys

import pytest

from lughus.core.errors import SafeToolError
from lughus.interfaces.mcp import StdioMCPClient, _RPCClient


class Immediate(_RPCClient):
    timeout = 0.02
    max_response_bytes = 10000
    on_tools_changed = None

    def __init__(self, result):
        self.result = result
        self._init_rpc()

    async def _ensure_connected(self):
        pass

    async def _write(self, payload):
        self._accept({"jsonrpc": "2.0", "id": payload["id"], "result": self.result})


@pytest.mark.asyncio
async def test_reply_during_write_is_not_lost() -> None:
    client = Immediate({"tools": []})
    assert await client._send_request("tools/list", {}) == {"tools": []}
    assert not client._pending


@pytest.mark.asyncio
async def test_error_flag_not_erased() -> None:
    with pytest.raises(SafeToolError):
        await Immediate(
            {"isError": True, "content": [{"type": "text", "text": "private detail"}]}
        ).call_tool("x", {})


@pytest.mark.asyncio
async def test_structured_content_preserved() -> None:
    assert await Immediate({"structuredContent": {"n": 1}, "content": []}).call_tool("x", {}) == {
        "n": 1
    }


@pytest.mark.asyncio
async def test_timeout_removes_pending() -> None:
    class Silent(Immediate):
        async def _write(self, payload):
            pass

    client = Silent({})
    with pytest.raises(TimeoutError):
        await client._send_request("tools/list", {})
    assert not client._pending


@pytest.mark.asyncio
async def test_close_fails_inflight() -> None:
    class Silent(Immediate):
        async def _write(self, payload):
            pass

    client = Silent({})
    task = asyncio.create_task(client._send_request("tools/list", {}))
    await asyncio.sleep(0)
    await client.close()
    with pytest.raises(ConnectionError):
        await task
    assert not client._pending


@pytest.mark.asyncio
async def test_native_stdio_drains_stderr() -> None:
    script = """import sys,json
for line in sys.stdin:
 r=json.loads(line)
 if 'id' not in r: continue
 sys.stderr.write('x'*100000);sys.stderr.flush()
 result={'protocolVersion':'2024-11-05'} if r['method']=='initialize' else {'tools':[]}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
"""
    async with StdioMCPClient([sys.executable, "-u", "-c", script]) as client:
        assert await client.list_tools() == ()
