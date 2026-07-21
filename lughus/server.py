"""One-call A2A server setup — AgentCard + Gateway + uvicorn."""

from __future__ import annotations

import asyncio
import hmac
import logging
import time
from collections import OrderedDict
from typing import Any

import uvicorn
from a2a.server.apps.jsonrpc.starlette_app import A2AStarletteApplication
from a2a.server.request_handlers.default_request_handler import (
    DefaultRequestHandler,
)
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import AgentCard
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .gateway import BaseGateway
from .telemetry import setup_telemetry
from .ui_server import _test_ui_routes

_logger = logging.getLogger(__name__)
_AUTH_EXEMPT_PATHS = {"/health", "/healthz"}


class RequestBodyTooLarge(Exception):
    """Raised when an ASGI request body exceeds the configured byte limit."""


class ProductionGuardMiddleware:
    """Small ASGI guard for public deployments.

    It enforces request body limits, optional bearer auth, and optional
    framework-level backpressure before the A2A app starts processing.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_body_bytes: int | None = None,
        bearer_token: str = "",
        max_concurrent_requests: int | None = None,
        max_queue_backlog: int | None = None,
        request_queue_timeout: float | None = 5.0,
        gateway: BaseGateway | None = None,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes if max_body_bytes and max_body_bytes > 0 else None
        self.bearer_token = bearer_token
        self.bearer_tokens = (
            {t.strip() for t in bearer_token.split(",") if t.strip()} if bearer_token else set()
        )
        self.gateway = gateway
        self.request_queue_timeout = (
            request_queue_timeout if request_queue_timeout and request_queue_timeout > 0 else 0.0
        )
        self._semaphore = (
            asyncio.Semaphore(max_concurrent_requests)
            if max_concurrent_requests and max_concurrent_requests > 0
            else None
        )
        self._max_pending_requests = (
            max_concurrent_requests + max(0, max_queue_backlog or 0)
            if max_concurrent_requests and max_concurrent_requests > 0
            else None
        )
        self._pending_requests = 0
        self._pending_lock = asyncio.Lock()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") == "lifespan":

            async def lifespan_receive() -> dict:
                msg = await receive()
                if msg.get("type") == "lifespan.shutdown":
                    if self.gateway and hasattr(self.gateway, "shutdown"):
                        await self.gateway.shutdown()
                return msg

            await self.app(scope, lifespan_receive, send)
            return

        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path") or ""
        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }

        if self.max_body_bytes is not None:
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    length = int(content_length)
                except ValueError:
                    response = JSONResponse({"error": "Invalid Content-Length"}, status_code=400)
                    await response(scope, receive, send)
                    return
                if length > self.max_body_bytes:
                    response = JSONResponse(
                        {"error": f"Request body exceeds {self.max_body_bytes} bytes"},
                        status_code=413,
                    )
                    await response(scope, receive, send)
                    return

        if self.bearer_tokens and path not in _AUTH_EXEMPT_PATHS:
            provided = headers.get("authorization", "")
            authorized = False
            if provided.startswith("Bearer "):
                token = provided[7:]
                for allowed in self.bearer_tokens:
                    if hmac.compare_digest(token, allowed):
                        authorized = True
                        break
            if not authorized:
                response = JSONResponse({"error": "Unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return

        body_bytes_seen = 0

        async def guarded_receive() -> dict:
            nonlocal body_bytes_seen
            message = await receive()
            if self.max_body_bytes is not None and message.get("type") == "http.request":
                body = message.get("body", b"")
                body_bytes_seen += len(body)
                if body_bytes_seen > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        if self._semaphore is None:
            try:
                await self.app(scope, guarded_receive, send)
            except RequestBodyTooLarge:
                response = JSONResponse(
                    {"error": f"Request body exceeds {self.max_body_bytes} bytes"},
                    status_code=413,
                )
                await response(scope, receive, send)
            return

        reject_for_backlog = False
        async with self._pending_lock:
            if (
                self._max_pending_requests is not None
                and self._pending_requests >= self._max_pending_requests
            ):
                reject_for_backlog = True
            else:
                self._pending_requests += 1

        if reject_for_backlog:
            response = JSONResponse({"error": "Server is busy"}, status_code=503)
            await response(scope, receive, send)
            return

        acquired = False
        try:
            if self.request_queue_timeout <= 0:
                if self._semaphore.locked():
                    response = JSONResponse({"error": "Server is busy"}, status_code=503)
                    await response(scope, receive, send)
                    return
                await self._semaphore.acquire()
            else:
                try:
                    await asyncio.wait_for(
                        self._semaphore.acquire(),
                        timeout=self.request_queue_timeout,
                    )
                except asyncio.TimeoutError:
                    response = JSONResponse({"error": "Server is busy"}, status_code=503)
                    await response(scope, receive, send)
                    return
            acquired = True

            try:
                await self.app(scope, guarded_receive, send)
            except RequestBodyTooLarge:
                response = JSONResponse(
                    {"error": f"Request body exceeds {self.max_body_bytes} bytes"},
                    status_code=413,
                )
                await response(scope, receive, send)
        finally:
            if acquired:
                self._semaphore.release()
            async with self._pending_lock:
                self._pending_requests -= 1


class BoundedInMemoryTaskStore(InMemoryTaskStore):
    """In-process task store with TTL and count-based eviction.

    This keeps quickstart deployments from growing memory without bound. It is
    still process-local; use a persistent SDK-compatible TaskStore for multiple
    replicas or durable task status.
    """

    durable = False
    shared_across_replicas = False
    atomic_updates = False
    supports_idempotency = False

    def __init__(
        self,
        *,
        ttl_seconds: float | None = 24 * 60 * 60,
        max_tasks: int | None = 10_000,
    ) -> None:
        super().__init__()
        self.ttl_seconds = ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        self.max_tasks = max_tasks if max_tasks and max_tasks > 0 else None
        self._saved_at: OrderedDict[str, float] = OrderedDict()

    def _cleanup_locked(self, now: float) -> None:
        if self.ttl_seconds is not None:
            while self._saved_at:
                task_id, saved_at = next(iter(self._saved_at.items()))
                if now - saved_at <= self.ttl_seconds:
                    break
                self.tasks.pop(task_id, None)
                self._saved_at.popitem(last=False)

        if self.max_tasks is not None:
            while len(self.tasks) > self.max_tasks and self._saved_at:
                task_id, _ = self._saved_at.popitem(last=False)
                self.tasks.pop(task_id, None)

    async def save(self, task: Any, context: Any | None = None) -> None:
        async with self.lock:
            now = time.monotonic()
            self._cleanup_locked(now)
            self.tasks[task.id] = task
            self._saved_at.pop(task.id, None)
            self._saved_at[task.id] = now
            self._cleanup_locked(now)

    async def get(self, task_id: str, context: Any | None = None) -> Any | None:
        async with self.lock:
            self._cleanup_locked(time.monotonic())
            return self.tasks.get(task_id)

    async def delete(self, task_id: str, context: Any | None = None) -> None:
        async with self.lock:
            self.tasks.pop(task_id, None)
            self._saved_at.pop(task_id, None)


async def _health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _is_production(settings: Any) -> bool:
    return str(getattr(settings, "environment", "")).strip().lower() == "production"


def _validate_production_config(
    *,
    gateway: BaseGateway,
    task_store: TaskStore | None,
    enable_test_ui: bool,
) -> None:
    """Fail fast for configurations that are unsafe in production mode."""
    settings = gateway.settings
    if not _is_production(settings):
        return

    errors = []
    if not getattr(settings, "api_bearer_token", ""):
        errors.append("API_BEARER_TOKEN must be set")
    if not getattr(settings, "public_url", ""):
        errors.append("PUBLIC_URL must be set")
    if enable_test_ui:
        errors.append("ENABLE_TEST_UI must be false")
    if task_store is None or not bool(getattr(task_store, "durable", False)):
        errors.append("a persistent task_store must be provided")
    if errors:
        raise RuntimeError("Invalid production configuration: " + "; ".join(errors))


def build_app(
    agent_card: AgentCard,
    gateway: BaseGateway,
    *,
    task_store: TaskStore | None = None,
    setup_otel: bool = True,
    enable_test_ui: bool = False,
) -> Any:
    """Build a complete A2A Starlette app without starting uvicorn.

    Args:
        agent_card: The AgentCard metadata.
        gateway: The BaseGateway executor instance.
        task_store: Optional custom task store. Defaults to BoundedInMemoryTaskStore.
        setup_otel: If True, calls setup_telemetry() automatically.
        enable_test_ui: If True, exposes the local testing interface at /ui.
    """
    if setup_otel:
        setup_telemetry(service_name=agent_card.name)

    _validate_production_config(
        gateway=gateway,
        task_store=task_store,
        enable_test_ui=enable_test_ui,
    )

    if task_store is None:
        _logger.warning(
            "Using bounded in-memory TaskStore; inject a persistent TaskStore for horizontally scaled production deployments."
        )
        task_store_ttl = getattr(gateway.settings, "task_store_ttl_seconds", 24 * 60 * 60)
        task_store_max = getattr(gateway.settings, "task_store_max_tasks", 10_000)
        if not isinstance(task_store_ttl, (int, float)):
            task_store_ttl = 24 * 60 * 60
        if not isinstance(task_store_max, int):
            task_store_max = 10_000
        task_store = BoundedInMemoryTaskStore(
            ttl_seconds=task_store_ttl,
            max_tasks=task_store_max,
        )

    handler = DefaultRequestHandler(
        agent_executor=gateway,
        task_store=task_store,
    )
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    )
    app = a2a_app.build()
    utility_routes = [
        Route("/health", _health),
        Route("/healthz", _health),
    ]
    if enable_test_ui:
        utility_routes.extend(_test_ui_routes(agent_card, gateway))
    app.routes[0:0] = utility_routes
    app.add_middleware(
        ProductionGuardMiddleware,
        max_body_bytes=getattr(gateway.settings, "max_http_body_bytes", None),
        bearer_token=getattr(gateway.settings, "api_bearer_token", ""),
        max_concurrent_requests=getattr(gateway.settings, "max_concurrent_requests", None),
        max_queue_backlog=getattr(gateway.settings, "max_queue_backlog", None),
        request_queue_timeout=getattr(gateway.settings, "request_queue_timeout", 5.0),
        gateway=gateway,
    )
    cors_origins = getattr(gateway.settings, "cors_origins", "")
    if cors_origins:
        from starlette.middleware.cors import CORSMiddleware

        origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
        if origins:
            allow_credentials = bool(getattr(gateway.settings, "cors_allow_credentials", False))
            if allow_credentials and "*" in origins:
                raise ValueError("CORS wildcard origins cannot be used with credentials")
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=allow_credentials,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type", "Accept"],
            )
    return app


def serve(
    agent_card: AgentCard,
    gateway: BaseGateway,
    host: str = "0.0.0.0",
    port: int = 8080,
    *,
    log_level: str = "INFO",
    task_store: TaskStore | None = None,
    setup_otel: bool = True,
    enable_test_ui: bool = False,
) -> None:
    """Start a complete A2A server with uvicorn.

    Args:
        agent_card: The AgentCard metadata.
        gateway: The BaseGateway executor instance.
        host: The host to bind to.
        port: The port to listen on.
        log_level: Log level string.
        task_store: Optional custom task store. Defaults to BoundedInMemoryTaskStore.
        setup_otel: If True, calls setup_telemetry() automatically.
        enable_test_ui: If True, exposes the local testing interface at /ui.
    """
    app = build_app(
        agent_card=agent_card,
        gateway=gateway,
        task_store=task_store,
        setup_otel=setup_otel,
        enable_test_ui=enable_test_ui,
    )
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        timeout_graceful_shutdown=30,
    )
