import json

import httpx
import pytest

from lughus.interfaces.a2a import A2AClient, A2AError


@pytest.mark.asyncio
async def test_native_message_and_task_methods() -> None:
    seen = []

    async def handler(request):
        body = json.loads(request.content)
        seen.append(body["method"])
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"kind": "task", "id": "t1", "status": {"state": "completed"}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async with A2AClient("https://agent.example/rpc", client=http) as client:
            assert (
                await client.send_message(
                    {"kind": "message", "role": "user", "messageId": "m1", "parts": []}
                )
            )["id"] == "t1"
            await client.get_task("t1")
            await client.cancel_task("t1")
        assert not http.is_closed
    assert seen == ["message/send", "tasks/get", "tasks/cancel"]


@pytest.mark.asyncio
async def test_rejects_response_identity_mismatch() -> None:
    async def handler(request):
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "wrong", "result": {}})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
        A2AClient("https://agent.example", client=http) as client,
    ):
        with pytest.raises(A2AError):
            await client.get_task("t1")


@pytest.mark.asyncio
async def test_native_stream() -> None:
    async def handler(request):
        body = json.loads(request.content)
        value = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "kind": "status-update",
                "taskId": "t1",
                "final": True,
                "status": {"state": "completed"},
            },
        }
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=("data: " + json.dumps(value) + "\n\n").encode(),
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http,
        A2AClient("https://agent.example", client=http) as client,
    ):
        events = [event async for event in client.resubscribe("t1")]
        assert events[-1]["final"] is True
