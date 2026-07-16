"""Local browser test UI routes and helpers."""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import html
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from importlib import resources
from typing import Any

from a2a.types import AgentCard
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ._threading import run_sync_in_thread
from .events import CompletionEvent, ProgressEvent
from .gateway import BaseGateway, _safe_filename, _validate_artifacts, _validate_objective
from .loop import collect_tool_events
from .telemetry import tracer

_logger = logging.getLogger(__name__)
_OTEL_MAX_BYTES = 1_000_000
_OTEL_TIMEOUT_SECONDS = 5.0


def _read_ui_asset(name: str) -> str:
    return resources.files("lughus").joinpath("ui", name).read_text(encoding="utf-8")


def _render_test_ui_html(agent_card: AgentCard) -> str:
    template = _read_ui_asset("test_ui.html")
    return (
        template
        .replace("__AGENT_NAME__", html.escape(agent_card.name))
        .replace("__AGENT_DESCRIPTION__", html.escape(agent_card.description or ""))
    )


def _is_safe_otel_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False

    # Check whitelist
    allowed_hosts_str = os.getenv("LUGHUS_ALLOWED_OTEL_HOSTS", "")
    allowed_hosts = {h.strip().lower() for h in allowed_hosts_str.split(",") if h.strip()}
    if hostname.lower() in allowed_hosts:
        return True

    try:
        ips = socket.getaddrinfo(hostname, None)
    except Exception:
        return False

    for item in ips:
        ip = item[4][0]
        if not isinstance(ip, str):
            continue
        # Allow IPv4/IPv6 loopback
        if ip in ("localhost", "127.0.0.1", "::1") or ip.startswith("127."):
            continue
        # Block private subnets (SSRF protection)
        # IPv4 private/local addresses:
        if (
            ip.startswith("10.") or
            ip.startswith("192.168.") or
            ip.startswith("169.254.") or
            (ip.startswith("172.") and len(ip.split(".")) > 1 and 16 <= int(ip.split(".")[1]) <= 31)
        ):
            return False
        # IPv6 link-local (fe80::) and unique local (fc00::, fd00::)
        if ip.startswith("fe80:") or ip.startswith("fc00:") or ip.startswith("fd00:"):
            return False
    return True


def _resolve_and_validate_otel_url(url: str) -> tuple[str, str]:
    """Resolve the hostname of the URL, validate it against SSRF, and return (rewritten_url, original_hostname)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Trace URL must be an absolute http(s) URL")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: missing hostname")

    # Check whitelist
    allowed_hosts_str = os.getenv("LUGHUS_ALLOWED_OTEL_HOSTS", "")
    allowed_hosts = {h.strip().lower() for h in allowed_hosts_str.split(",") if h.strip()}

    try:
        ips = socket.getaddrinfo(hostname, None)
    except Exception as exc:
        raise ValueError(f"Failed to resolve host '{hostname}': {exc}") from exc

    resolved_ip = None
    for item in ips:
        ip = item[4][0]
        if not isinstance(ip, str):
            continue

        if hostname.lower() not in allowed_hosts:
            # Allow IPv4/IPv6 loopback
            if ip in ("localhost", "127.0.0.1", "::1") or ip.startswith("127."):
                pass
            # Block private subnets (SSRF protection)
            elif (
                ip.startswith("10.") or
                ip.startswith("192.168.") or
                ip.startswith("169.254.") or
                (ip.startswith("172.") and len(ip.split(".")) > 1 and 16 <= int(ip.split(".")[1]) <= 31)
            ):
                raise ValueError("Trace URL destination is not allowed (SSRF protection)")
            # IPv6 link-local (fe80::) and unique local (fc00::, fd00::)
            elif ip.startswith("fe80:") or ip.startswith("fc00:") or ip.startswith("fd00:"):
                raise ValueError("Trace URL destination is not allowed (SSRF protection)")

        if resolved_ip is None:
            resolved_ip = ip

    if not resolved_ip:
        raise ValueError(f"No IP addresses resolved for host '{hostname}'")

    # Rewrite netloc with resolved IP to prevent TOCTOU DNS rebinding (only for http to avoid breaking TLS)
    if parsed.scheme == "http":
        port = parsed.port
        new_netloc = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
        if port:
            new_netloc = f"{new_netloc}:{port}"
        rewritten_parsed = parsed._replace(netloc=new_netloc)
        return rewritten_parsed.geturl(), hostname
    else:
        return url, hostname


def _fetch_otel_url(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Trace URL must be an absolute http(s) URL")

    try:
        rewritten_url, original_host = _resolve_and_validate_otel_url(url)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    request = urllib.request.Request(
        rewritten_url,
        headers={
            "Host": original_host,
            "accept": "application/json, text/plain;q=0.9, */*;q=0.1"
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_OTEL_TIMEOUT_SECONDS) as response:
            data = response.read(_OTEL_MAX_BYTES + 1)
            if len(data) > _OTEL_MAX_BYTES:
                raise ValueError(f"Trace response exceeds {_OTEL_MAX_BYTES} bytes")
            content_type = response.headers.get("content-type", "")
            status_code = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Trace endpoint returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Trace endpoint is unreachable: {exc.reason}") from exc

    text = data.decode("utf-8", errors="replace")
    parsed_json: Any = None
    if "json" in content_type.lower():
        try:
            parsed_json = json.loads(text)
        except ValueError:
            parsed_json = None
    return {
        "url": url,
        "status_code": status_code,
        "content_type": content_type,
        "text": text,
        "json": parsed_json,
    }


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
    return (
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )


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
    otel_attributes.update({
        "lughus.ui.request_elapsed_ms": round(request_elapsed_ms, 2),
        "lughus.ui.tool_call_count": len(tool_results),
        "lughus.ui.tool_error_count": tool_errors,
    })

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
    if raw_files is None:
        return []
    if not isinstance(raw_files, list):
        raise ValueError("files must be a list")
    if len(raw_files) > gateway.settings.max_files:
        raise ValueError(f"Too many files: max {gateway.settings.max_files}")

    files: list[tuple[bytes, str, str]] = []
    total_bytes = 0
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ValueError(f"files[{index}] must be an object")
        name = _safe_filename(str(item.get("name") or "file"))
        mime_type = str(item.get("mime_type") or "application/octet-stream")
        encoded = item.get("content_base64")
        if not isinstance(encoded, str):
            raise ValueError(f"files[{index}].content_base64 must be a string")
        try:
            data = await run_sync_in_thread(
                lambda: base64.b64decode(encoded, validate=True),
                max_workers=gateway.settings.max_sync_thread_workers,
            )
        except binascii.Error as exc:
            raise ValueError(f"files[{index}] is not valid base64") from exc
        if len(data) > gateway.settings.max_file_bytes:
            raise ValueError(
                f"File '{name}' exceeds max size {gateway.settings.max_file_bytes} bytes"
            )
        total_bytes += len(data)
        if total_bytes > gateway.settings.max_request_bytes:
            raise ValueError(
                f"Files exceed max request size {gateway.settings.max_request_bytes} bytes"
            )
        files.append((data, mime_type, name))
    return files


def _test_ui_routes(agent_card: AgentCard, gateway: BaseGateway) -> list[Route]:
    async def page(request: Request) -> HTMLResponse:
        return HTMLResponse(_render_test_ui_html(agent_card))

    async def css(request: Request) -> Response:
        return Response(_read_ui_asset("test_ui.css"), media_type="text/css")

    async def js(request: Request) -> Response:
        return Response(_read_ui_asset("test_ui.js"), media_type="application/javascript")

    async def _parse_run_request(
        request: Request,
    ) -> tuple[str, list[tuple[bytes, str, str]]] | JSONResponse:
        try:
            payload = await request.json()
        except Exception:
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

    async def run(request: Request) -> JSONResponse:
        parsed = await _parse_run_request(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        objective, files = parsed

        events: list[dict[str, Any]] = []
        completion_metadata: dict[str, Any] = {}
        started_at = time.perf_counter()
        timeout_ctx = (
            asyncio.timeout(gateway.settings.agent_timeout)
            if gateway.settings.agent_timeout > 0
            else contextlib.nullcontext()
        )
        try:
            with tracer.start_as_current_span("lughus.ui.run") as span:
                span.set_attribute("lughus.objective_len", len(objective))
                span.set_attribute("lughus.file_count", len(files))
                with collect_tool_events(events.append):
                    async with timeout_ctx:
                        async for event in gateway.handle(objective, files):
                            if isinstance(event, ProgressEvent):
                                events.append({"type": "progress", "text": event.text})
                            elif isinstance(event, CompletionEvent):
                                completion_metadata = dict(event.metadata or {})
                                events.append(_completion_event(event, gateway.settings))

                telemetry = _telemetry_event(
                    metadata=completion_metadata,
                    events=events,
                    request_elapsed_ms=(time.perf_counter() - started_at) * 1000,
                )
                if telemetry is not None:
                    for key, value in telemetry["otel_attributes"].items():
                        if isinstance(value, (str, int, float, bool)):
                            span.set_attribute(key, value)
                    events.append(telemetry)
        except TimeoutError:
            return JSONResponse(
                {"error": f"Agent execution timed out after {gateway.settings.agent_timeout}s"},
                status_code=504,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            _logger.exception("Test UI run failed")
            return JSONResponse({"error": str(exc)}, status_code=500)

        return JSONResponse({"events": events})

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
                                        _enqueue_nowait(
                                            _completion_event(event, gateway.settings)
                                        )

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
                    _enqueue_nowait({
                        "type": "error",
                        "text": f"Agent execution timed out after {gateway.settings.agent_timeout}s",
                    })
                except ValueError as exc:
                    _enqueue_nowait({"type": "error", "text": str(exc)})
                except Exception as exc:
                    _logger.exception("Test UI stream failed")
                    _enqueue_nowait({"type": "error", "text": str(exc)})
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

    async def otel_traces(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        url = str(payload.get("url") or "").strip()
        if not url:
            return JSONResponse({"error": "Trace URL is required"}, status_code=400)
        try:
            result = await run_sync_in_thread(
                lambda: _fetch_otel_url(url),
                max_workers=gateway.settings.max_sync_thread_workers,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            _logger.exception("Test UI trace fetch failed")
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(result)

    return [
        Route("/ui", page, methods=["GET"]),
        Route("/ui/run", run, methods=["POST"]),
        Route("/ui/otel/traces", otel_traces, methods=["POST"]),
        Route("/ui/stream", stream, methods=["POST"]),
        Route("/ui/assets/test_ui.css", css, methods=["GET"]),
        Route("/ui/assets/test_ui.js", js, methods=["GET"]),
    ]


# Backward-compatible aliases for private tests/users that imported these names
# from lughus.server before the UI module was split out.
_test_ui_html = _render_test_ui_html
_decode_test_ui_files = _decode_files
_fetch_test_ui_otel_url = _fetch_otel_url
_test_ui_telemetry_event = _telemetry_event
