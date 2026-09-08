"""Small shared HTTP/SSE safety primitives; no provider dependency."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlsplit


def origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A concrete HTTP(S) URL is required")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL credentials and fragments are forbidden")
    if "\\" in url or any(ord(char) < 33 for char in url):
        raise ValueError("Invalid URL characters")
    return (
        parsed.scheme,
        parsed.hostname.lower(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


def same_origin_url(base: str, target: str) -> str:
    resolved = urljoin(base, target)
    if origin(resolved) != origin(base):
        raise ValueError("Cross-origin endpoint is forbidden")
    return resolved


async def read_json(response: Any, max_bytes: int) -> dict[str, Any]:
    response.raise_for_status()
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise ValueError("HTTP response exceeds configured size limit")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


async def sse_events(response: Any, max_event_bytes: int) -> AsyncIterator[tuple[str, str]]:
    """Parse UTF-8 SSE including multi-line data, bounded before buffering lines."""
    response.raise_for_status()
    pending = bytearray()
    event = "message"
    data: list[str] = []
    used = 0
    async for chunk in response.aiter_bytes():
        # Consume byte by byte so a newline-free response cannot grow without bound.
        for byte in chunk:
            pending.append(byte)
            used += 1
            if used > max_event_bytes:
                raise ValueError("SSE event exceeds configured size limit")
            if byte != 10:
                continue
            line = bytes(pending).decode("utf-8").rstrip("\r\n")
            pending.clear()
            if not line:
                if data:
                    yield event, "\n".join(data)
                event, data, used = "message", [], 0
            elif not line.startswith(":"):
                key, sep, value = line.partition(":")
                if sep and value.startswith(" "):
                    value = value[1:]
                if key == "event":
                    event = value or "message"
                elif key == "data":
                    data.append(value)
    # An incomplete final event is intentionally not dispatched (SSE framing).
