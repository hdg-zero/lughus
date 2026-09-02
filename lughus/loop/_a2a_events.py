"""Emission of A2A exchange events to the developer console.

Delegation tools (or any code that calls a remote A2A agent) can emit
``a2a_request`` / ``a2a_response`` events so the UI shows the exact
payload sent and the full response received — including artifacts as
downloadable base64 files.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from ._execute import _emit_tool_event

__all__ = ["emit_a2a_request", "emit_a2a_response"]


def _encode_artifact(data: bytes, name: str, mime: str) -> dict[str, str]:
    return {
        "name": name,
        "mime_type": mime,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }


def emit_a2a_request(
    *,
    target_agent: str,
    url: str,
    method: str = "message/send",
    objective: str,
    files: list[tuple[bytes, str, str]] | None = None,
    tool_name: str | None = None,
) -> None:
    """Emit an ``a2a_request`` event describing the outbound A2A call."""
    event: dict[str, Any] = {
        "type": "a2a_request",
        "tool_name": tool_name or "",
        "target_agent": target_agent,
        "url": url,
        "method": method,
        "objective": objective,
        "file_count": len(files or []),
        "files": [
            {"name": name, "mime_type": mime, "size_bytes": len(data)}
            for data, mime, name in (files or [])
        ],
        "elapsed_ms": 0.0,
    }
    _emit_tool_event(event)


def emit_a2a_response(
    *,
    target_agent: str,
    url: str,
    status: str = "ok",
    text: str = "",
    artifacts: list[tuple[bytes, str, str]] | None = None,
    remote_task_id: str | None = None,
    error_code: str | None = None,
    elapsed_ms: float | None = None,
    tool_name: str | None = None,
) -> None:
    """Emit an ``a2a_response`` event with the full reply from the remote agent.

    *artifacts* entries are ``(raw_bytes, mime_type, name)`` tuples; they are
    base64-encoded so the UI can offer them as downloads, exactly like the
    artifacts of a completion event.
    """
    event: dict[str, Any] = {
        "type": "a2a_response",
        "tool_name": tool_name or "",
        "target_agent": target_agent,
        "url": url,
        "status": status,
        "text": text,
        "artifacts": [_encode_artifact(data, name, mime) for data, mime, name in (artifacts or [])],
        "remote_task_id": remote_task_id or "",
        "error_code": error_code or "",
        "elapsed_ms": round(elapsed_ms if elapsed_ms is not None else 0.0, 2),
        "_ts": time.time(),
    }
    _emit_tool_event(event)
