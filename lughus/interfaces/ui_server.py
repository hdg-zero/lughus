"""Local browser test UI routes and helpers."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import json
import logging
import time
from collections.abc import AsyncIterator
from importlib import resources
from pathlib import Path
from typing import Any

from a2a.types import AgentCard
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..core.errors import ApprovalRequired, ApprovalRequiredGroup, LoopLimitError, LughusError
from ..core.events import CompletionEvent, ProgressEvent
from ..engine.files import decode_files_payload
from ..infra.telemetry import tracer
from ..loop import collect_tool_events
from .gateway import BaseGateway, _validate_artifacts, _validate_objective

__all__ = [
    "shutdown_ui_server",
]

_logger = logging.getLogger(__name__)

_ASSET_MIME_TYPES: dict[str, str] = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".svg": "image/svg+xml",
    ".html": "text/html",
    ".json": "application/json",
}


def shutdown_ui_server() -> None:
    """Shutdown background resources allocated for the developer console."""


def _read_ui_asset(name: str) -> str:
    return resources.files("lughus").joinpath("ui", name).read_text(encoding="utf-8")


def _render_console_html(agent_card: AgentCard) -> str:
    template = _read_ui_asset("console.html")
    return template.replace("__AGENT_NAME__", html.escape(agent_card.name)).replace(
        "__AGENT_DESCRIPTION__", html.escape(agent_card.description or "")
    )


def _completion_event(event: CompletionEvent, settings: Any) -> dict[str, Any]:
    _validate_artifacts(event.artifacts, settings)
    return {
        "type": "completion",
        "text": event.text,
        "artifacts": [
            {
                "name": artifact.name,
                "mime_type": artifact.mime_type,
                "data_base64": base64.b64encode(artifact.data).decode("ascii"),
            }
            for artifact in event.artifacts
        ],
    }


def _json_line(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def _telemetry_event(
    *,
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    request_elapsed_ms: float,
) -> dict[str, Any] | None:
    tool_results = [event for event in events if event.get("type") == "tool_result"]
    if not metadata and not tool_results:
        return None

    tool_names = sorted(
        {
            str(event.get("tool_name"))
            for event in events
            if event.get("type") in {"tool_start", "tool_result"} and event.get("tool_name")
        }
    )
    tool_elapsed = sum(float(event.get("elapsed_ms") or 0) for event in tool_results)
    tool_errors = sum(1 for event in tool_results if event.get("status") == "error")
    otel_attributes = dict(metadata.get("otel_attributes") or {})
    otel_attributes.update(
        {
            "lughus.ui.request_elapsed_ms": round(request_elapsed_ms, 2),
            "lughus.ui.tool_call_count": len(tool_results),
            "lughus.ui.tool_error_count": tool_errors,
        }
    )

    return {
        "type": "telemetry",
        "model": metadata.get("model", ""),
        "iterations": metadata.get("iterations"),
        "loop_elapsed_s": metadata.get("elapsed_s"),
        "request_elapsed_ms": round(request_elapsed_ms, 2),
        "tokens": {
            "prompt": metadata.get("prompt_tokens", 0),
            "completion": metadata.get("completion_tokens", 0),
            "cached": metadata.get("cached_tokens", 0),
            "total": metadata.get("total_tokens", 0),
        },
        "tools": {
            "count": len(tool_results),
            "errors": tool_errors,
            "elapsed_ms": round(tool_elapsed, 2),
            "names": tool_names,
        },
        "otel_attributes": otel_attributes,
    }


async def _decode_files(
    raw_files: Any,
    gateway: BaseGateway,
) -> list[tuple[bytes, str, str]]:
    return await decode_files_payload(raw_files, gateway.settings)


def _console_routes(agent_card: AgentCard, gateway: BaseGateway) -> list[Route]:
    async def page(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_console_html(agent_card))

    async def _parse_run_request(
        request: Request,
    ) -> tuple[str, list[tuple[bytes, str, str]]] | JSONResponse:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

        objective = str(payload.get("objective") or "")
        try:
            _validate_objective(objective, gateway.settings)
            files = await _decode_files(payload.get("files"), gateway)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return objective, files

    async def stream(request: Request) -> JSONResponse | StreamingResponse:
        parsed = await _parse_run_request(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        objective, files = parsed

        async def _lines() -> AsyncIterator[bytes]:
            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
            events: list[dict[str, Any]] = []
            completion_metadata: dict[str, Any] = {}
            started_at = time.perf_counter()

            def _enqueue_nowait(item: dict[str, Any]) -> None:
                events.append(item)
                queue.put_nowait(item)

            async def _produce() -> None:
                nonlocal completion_metadata
                timeout_ctx = (
                    asyncio.timeout(gateway.settings.agent_timeout)
                    if gateway.settings.agent_timeout > 0
                    else contextlib.nullcontext()
                )
                try:
                    with tracer.start_as_current_span("lughus.ui.stream") as span:
                        span.set_attribute("lughus.objective_len", len(objective))
                        span.set_attribute("lughus.file_count", len(files))
                        with collect_tool_events(_enqueue_nowait):
                            async with timeout_ctx:
                                async for event in gateway.handle(objective, files):
                                    if isinstance(event, ProgressEvent):
                                        _enqueue_nowait({"type": "progress", "text": event.text})
                                    elif isinstance(event, CompletionEvent):
                                        completion_metadata = dict(event.metadata or {})
                                        _enqueue_nowait(_completion_event(event, gateway.settings))

                        telemetry = _telemetry_event(
                            metadata=completion_metadata,
                            events=events,
                            request_elapsed_ms=(time.perf_counter() - started_at) * 1000,
                        )
                        if telemetry is not None:
                            for key, value in telemetry["otel_attributes"].items():
                                if isinstance(value, (str, int, float, bool)):
                                    span.set_attribute(key, value)
                            _enqueue_nowait(telemetry)
                except TimeoutError:
                    _enqueue_nowait(
                        {
                            "type": "error",
                            "code": "agent_timeout",
                            "text": (
                                f"Agent execution timed out after {gateway.settings.agent_timeout}s"
                            ),
                        }
                    )
                except (ApprovalRequired, ApprovalRequiredGroup) as exc:
                    requests = exc.requests if isinstance(exc, ApprovalRequiredGroup) else [exc]
                    for req in requests:
                        _enqueue_nowait(
                            {
                                "type": "error",
                                "code": "approval_required",
                                "request_id": getattr(req, "request_id", "") or "",
                                "tool_name": getattr(req, "tool_name", "") or "",
                                "text": (
                                    f"Tool '{req.tool_name}' requires human approval. "
                                    "Decide below; then re-run the objective."
                                ),
                            }
                        )
                except LoopLimitError as exc:
                    _enqueue_nowait(
                        {
                            "type": "error",
                            "code": "loop_limit",
                            "text": (
                                f"{exc} The agent kept requesting tool calls without producing "
                                "a final answer — try a more specific objective, raise the "
                                "iteration limit, or simplify the task."
                            ),
                        }
                    )
                except LughusError as exc:
                    _enqueue_nowait({"type": "error", "code": type(exc).__name__, "text": str(exc)})
                except ValueError as exc:
                    _enqueue_nowait({"type": "error", "code": "invalid_input", "text": str(exc)})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _logger.exception("Developer console stream failed")
                    _enqueue_nowait(
                        {
                            "type": "error",
                            "code": "internal_error",
                            "text": "An internal error occurred; see server logs for details.",
                        }
                    )
                finally:
                    queue.put_nowait(None)

            producer = asyncio.create_task(_produce())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield _json_line(item)
            finally:
                if not producer.done():
                    producer.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await producer

        return StreamingResponse(
            _lines(),
            media_type="application/x-ndjson",
            headers={"cache-control": "no-cache"},
        )

    async def serve_asset(request: Request) -> Response:
        filename = request.path_params.get("filename", "")
        safe_filename = Path(filename).name
        try:
            content = _read_ui_asset(safe_filename)
            suffix = Path(safe_filename).suffix.lower()
            media_type = _ASSET_MIME_TYPES.get(suffix, "application/octet-stream")
            return Response(content, media_type=media_type)
        except (FileNotFoundError, IsADirectoryError, OSError, UnicodeError):
            return Response("Asset not found", status_code=404)

    async def serve_favicon(request: Request) -> Response:
        try:
            content = _read_ui_asset("logo.svg")
            return Response(content, media_type="image/svg+xml")
        except (FileNotFoundError, OSError, UnicodeError):
            return Response("Favicon not found", status_code=404)

    async def decide_approval(request: Request) -> JSONResponse:
        """Record a human approve/reject decision for a pending request.

        The decision is stored in the gateway's approval store when one is
        configured; the response mirrors the resulting record so the UI can
        render the outcome without a second fetch.
        """
        store = getattr(gateway, "approval_store", None)
        if store is None:
            return JSONResponse(
                {"error": "No approval store configured on this gateway"},
                status_code=501,
            )
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

        request_id = str(request.path_params.get("request_id", ""))
        approved = payload.get("approved")
        subject = str(payload.get("subject") or "ui-operator")
        if not isinstance(approved, bool):
            return JSONResponse({"error": "'approved' boolean required"}, status_code=400)

        from ..governance.approval import ApprovalStatus

        current = await store.get(request_id)
        if current is None:
            return JSONResponse(
                {"error": f"Unknown approval request '{request_id}'"}, status_code=404
            )

        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        updated = await store.decide(request_id, status, subject)
        return JSONResponse(
            {
                "request_id": updated.request_id,
                "tool_name": updated.tool_name,
                "status": str(updated.status.value),
                "decided_by": updated.decided_by,
                "decided_at": updated.decided_at,
            }
        )

    async def get_approval(request: Request) -> JSONResponse:
        store = getattr(gateway, "approval_store", None)
        if store is None:
            return JSONResponse(
                {"error": "No approval store configured on this gateway"},
                status_code=501,
            )
        request_id = str(request.path_params.get("request_id", ""))
        current = await store.get(request_id)
        if current is None:
            return JSONResponse(
                {"error": f"Unknown approval request '{request_id}'"}, status_code=404
            )
        return JSONResponse(
            {
                "request_id": current.request_id,
                "tool_name": current.tool_name,
                "run_id": current.run_id,
                "risk": current.risk,
                "status": str(current.status.value),
            }
        )

    return [
        Route("/ui", page, methods=["GET"]),
        Route("/ui/stream", stream, methods=["POST"]),
        Route("/ui/approvals/{request_id}", decide_approval, methods=["POST"]),
        Route("/ui/approvals/{request_id}", get_approval, methods=["GET"]),
        Route("/ui/assets/{filename:path}", serve_asset, methods=["GET"]),
        Route("/favicon.ico", serve_favicon, methods=["GET"]),
    ]
