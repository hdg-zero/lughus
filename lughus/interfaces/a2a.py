"""Native A2A JSON-RPC 0.3 HTTP client, independent of the A2A server SDK."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import httpx

from ..engine.delegation import DelegationRequest, DelegationResult
from ..infra.http import origin, read_json, same_origin_url, sse_events


class A2AError(RuntimeError):
    """A transport or JSON-RPC failure; remote diagnostics stay outside model output."""


class A2AClient:
    """One explicitly trusted endpoint and caller-owned credentials.

    No automatic retries for mutations, no URL following in remote artifacts,
    no auth forwarding across origins, no implicit delegation to model-chosen URLs.
    Supplied HTTP clients remain caller-owned.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        max_response_bytes: int = 2_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        scheme, host, _ = origin(endpoint)
        if scheme != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Cleartext HTTP is restricted to loopback development")
        if timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("Timeout and response limit must be positive")
        self.endpoint, self.timeout = endpoint, timeout
        self.max_response_bytes = max_response_bytes
        self._headers = dict(headers or {})
        self._owned = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        )

    @staticmethod
    def _result(value: dict[str, Any], request_id: str) -> dict[str, Any]:
        if value.get("jsonrpc") != "2.0" or value.get("id") != request_id:
            raise A2AError("Invalid JSON-RPC response identity")
        if "error" in value:
            raise A2AError("Remote A2A request failed")
        result = value.get("result")
        if not isinstance(result, dict):
            raise A2AError("Missing A2A result object")
        return result

    async def _rpc(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        request_id = uuid4().hex
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
        async with asyncio.timeout(self.timeout):
            async with self._client.stream(
                "POST",
                self.endpoint,
                json=payload,
                headers=self._headers,
                follow_redirects=False,
            ) as response:
                return self._result(await read_json(response, self.max_response_bytes), request_id)

    async def _stream(
        self, method: str, params: Mapping[str, Any]
    ) -> AsyncIterator[dict[str, Any]]:
        request_id = uuid4().hex
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}
        async with asyncio.timeout(self.timeout):
            async with self._client.stream(
                "POST",
                self.endpoint,
                json=payload,
                headers={**self._headers, "Accept": "text/event-stream"},
                follow_redirects=False,
            ) as response:
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise A2AError("Expected an SSE response")
                async for _event, data in sse_events(response, self.max_response_bytes):
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise A2AError("Invalid SSE response object")
                    result = self._result(value, request_id)
                    yield result
                    if result.get("final") is True:
                        return

    async def agent_card(self, path: str = "/.well-known/agent-card.json") -> dict[str, Any]:
        url = same_origin_url(self.endpoint, path)
        async with asyncio.timeout(self.timeout):
            async with self._client.stream(
                "GET", url, headers=self._headers, follow_redirects=False
            ) as response:
                card = await read_json(response, self.max_response_bytes)
        # Discovery is informational, never an automatic credential-bearing redirect.
        if "url" in card:
            same_origin_url(self.endpoint, str(card["url"]))
        return card

    async def send_message(
        self, message: Mapping[str, Any], *, blocking: bool = True
    ) -> dict[str, Any]:
        return await self._rpc(
            "message/send", {"message": dict(message), "configuration": {"blocking": blocking}}
        )

    def stream_message(self, message: Mapping[str, Any]) -> AsyncIterator[dict[str, Any]]:
        return self._stream("message/stream", {"message": dict(message)})

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("tasks/get", {"id": task_id})

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("tasks/cancel", {"id": task_id})

    def resubscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        return self._stream("tasks/resubscribe", {"id": task_id})

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        if request.target_agent != self.endpoint:
            raise ValueError("Delegation target must match the configured endpoint")
        message = {
            "kind": "message",
            "role": "user",
            "messageId": uuid4().hex,
            "parts": [{"kind": "text", "text": request.objective}],
            "metadata": {
                "lughus": {
                    "parent_run_id": request.parent_run_id,
                    "skill": request.skill,
                    "causal_chain": [*request.causal_chain, request.target_agent],
                    "permitted_data": dict(request.permitted_data),
                }
            },
        }
        result = await self.send_message(message)
        if result.get("kind") == "message":
            return DelegationResult(
                str(result.get("messageId", "")), "completed", ({"parts": result.get("parts", [])},)
            )
        status = result.get("status", {})
        if not isinstance(status, dict) or not result.get("id"):
            raise A2AError("Invalid task response")
        return DelegationResult(
            str(result["id"]),
            str(status.get("state", "unknown")),
            tuple(result.get("artifacts", [])),
        )

    async def close(self) -> None:
        if self._owned:
            await self._client.aclose()

    async def __aenter__(self) -> A2AClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
