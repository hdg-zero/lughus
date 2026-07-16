"""Tests for serve() server entrypoint (J2-3)."""
from __future__ import annotations

import json
import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
import pytest
from starlette.requests import Request

from lughus import Artifact, BaseSettings, CompletionEvent, ProgressEvent, build_app, serve
from lughus.gateway import BaseGateway
from lughus.server import BoundedInMemoryTaskStore, ProductionGuardMiddleware, _test_ui_routes


class MockGateway(BaseGateway):
    async def handle(self, objective, files):
        pass


class UIGateway(BaseGateway):
    async def handle(
        self,
        objective: str,
        files: list[tuple[bytes, str, str]],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        yield ProgressEvent(f"received:{objective}:{len(files)}")
        yield CompletionEvent(
            text="done",
            artifacts=[Artifact(data=b"hello", mime_type="text/plain", name="result.txt")],
        )


class TelemetryUIGateway(BaseGateway):
    async def handle(
        self,
        objective: str,
        files: list[tuple[bytes, str, str]],
    ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
        yield CompletionEvent(
            text="done",
            metadata={
                "model": "test/model",
                "iterations": 2,
                "elapsed_s": 0.25,
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "cached_tokens": 3,
                "total_tokens": 18,
                "otel_attributes": {
                    "gen_ai.request.model": "test/model",
                    "gen_ai.usage.total_tokens": 18,
                },
            },
        )


def _agent_card() -> AgentCard:
    return AgentCard(
        name="test-agent",
        version="0.1.0",
        url="http://localhost:8080",
        description="Test agent.",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="test",
                name="Test",
                description="Test skill.",
                tags=["test"],
            )
        ],
        capabilities=AgentCapabilities(streaming=True),
    )


def _request(method: str, path: str, payload: dict | None = None) -> Request:
    body = json.dumps(payload or {}).encode("utf-8")
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )


async def _call_asgi(app, *, method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None, body: bytes = b"") -> tuple[int, bytes]:
    sent_messages: list[dict] = []
    received = False

    async def receive() -> dict:
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        sent_messages.append(message)

    await app(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
        },
        receive,
        send,
    )
    status = next(m["status"] for m in sent_messages if m["type"] == "http.response.start")
    response_body = b"".join(
        m.get("body", b"") for m in sent_messages if m["type"] == "http.response.body"
    )
    return status, response_body


async def _ok_app(scope, receive, send) -> None:
    response = {"type": "http.response.start", "status": 200, "headers": []}
    await send(response)
    await send({"type": "http.response.body", "body": b"ok"})


async def _read_body_app(scope, receive, send) -> None:
    while True:
        message = await receive()
        if message.get("type") != "http.request" or not message.get("more_body", False):
            break
    response = {"type": "http.response.start", "status": 200, "headers": []}
    await send(response)
    await send({"type": "http.response.body", "body": b"ok"})


@patch("lughus.server.uvicorn.run")
@patch("lughus.server.setup_telemetry")
@patch("lughus.server.DefaultRequestHandler")
@patch("lughus.server.A2AStarletteApplication")
def test_serve_calls(
    mock_app_class,
    mock_handler_class,
    mock_setup_telemetry,
    mock_uvicorn_run,
) -> None:
    """serve() sets up request handler and telemetry properly."""
    # Use a MagicMock to avoid strict pydantic validation of AgentCard
    agent_card = MagicMock(spec=AgentCard)
    agent_card.name = "test-agent"

    gateway = MockGateway(llm=MagicMock(), settings=MagicMock())
    custom_task_store = MagicMock()

    # Case 1: Custom task store and setup_otel=True
    serve(
        agent_card=agent_card,
        gateway=gateway,
        task_store=custom_task_store,
        setup_otel=True,
    )

    mock_setup_telemetry.assert_called_once_with(service_name="test-agent")
    mock_handler_class.assert_called_once_with(
        agent_executor=gateway,
        task_store=custom_task_store,
    )
    mock_uvicorn_run.assert_called_once()

    # Reset mocks
    mock_setup_telemetry.reset_mock()
    mock_handler_class.reset_mock()

    # Case 2: Default task store and setup_otel=False
    serve(
        agent_card=agent_card,
        gateway=gateway,
        setup_otel=False,
    )

    mock_setup_telemetry.assert_not_called()
    # Should call with DefaultInMemoryTaskStore (mock_handler_class first argument)
    assert mock_handler_class.call_args[1]["agent_executor"] == gateway
    # task_store was not custom, so it falls back to InMemoryTaskStore
    assert mock_handler_class.call_args[1]["task_store"] is not None


def test_build_app_can_expose_test_ui() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    app = build_app(_agent_card(), gateway, setup_otel=False, enable_test_ui=True)

    assert [route.path for route in app.routes[:6]] == [
        "/health",
        "/healthz",
        "/ui",
        "/ui/run",
        "/ui/otel/traces",
        "/ui/stream",
    ]


@pytest.mark.asyncio
async def test_production_guard_enforces_bearer_token() -> None:
    app = ProductionGuardMiddleware(_ok_app, bearer_token="secret")

    status, _ = await _call_asgi(app, method="GET", path="/health")
    assert status == 200
    status, _ = await _call_asgi(app, method="GET", path="/ui")
    assert status == 401
    status, body = await _call_asgi(
        app,
        method="GET",
        path="/ui",
        headers=[(b"authorization", b"Bearer secret")],
    )
    assert status == 200
    assert body == b"ok"


@pytest.mark.asyncio
async def test_production_guard_rejects_oversized_content_length() -> None:
    app = ProductionGuardMiddleware(_ok_app, max_body_bytes=4)

    status, body = await _call_asgi(
        app,
        method="POST",
        path="/",
        headers=[(b"content-length", b"5")],
        body=b"12345",
    )

    assert status == 413
    assert b"Request body exceeds" in body


@pytest.mark.asyncio
async def test_production_guard_rejects_streamed_body_without_content_length() -> None:
    app = ProductionGuardMiddleware(_read_body_app, max_body_bytes=4)

    status, body = await _call_asgi(
        app,
        method="POST",
        path="/",
        body=b"12345",
    )

    assert status == 413
    assert b"Request body exceeds" in body


@pytest.mark.asyncio
async def test_production_guard_limits_concurrent_requests() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_app(scope, receive, send) -> None:
        started.set()
        await release.wait()
        await _ok_app(scope, receive, send)

    app = ProductionGuardMiddleware(
        slow_app,
        max_concurrent_requests=1,
        request_queue_timeout=0,
    )
    first = asyncio.create_task(_call_asgi(app, method="GET", path="/"))
    await started.wait()

    status, body = await _call_asgi(app, method="GET", path="/")

    release.set()
    await first
    assert status == 503
    assert b"Server is busy" in body


@pytest.mark.asyncio
async def test_production_guard_rejects_requests_beyond_backlog() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_app(scope, receive, send) -> None:
        started.set()
        await release.wait()
        await _ok_app(scope, receive, send)

    app = ProductionGuardMiddleware(
        slow_app,
        max_concurrent_requests=1,
        max_queue_backlog=1,
        request_queue_timeout=1.0,
    )
    first = asyncio.create_task(_call_asgi(app, method="GET", path="/"))
    await started.wait()
    second = asyncio.create_task(_call_asgi(app, method="GET", path="/"))
    await asyncio.sleep(0)

    status, body = await _call_asgi(app, method="GET", path="/")

    release.set()
    await first
    await second
    assert status == 503
    assert b"Server is busy" in body


def test_build_app_rejects_unsafe_production_config(monkeypatch) -> None:
    monkeypatch.setenv("LUGHUS_ENV", "production")
    monkeypatch.delenv("API_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())

    with pytest.raises(RuntimeError, match="Invalid production configuration"):
        build_app(_agent_card(), gateway, setup_otel=False)


@pytest.mark.asyncio
async def test_test_ui_page_renders_agent_metadata() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    page = _test_ui_routes(_agent_card(), gateway)[0].endpoint

    response = await page(_request("GET", "/ui"))

    assert response.status_code == 200
    assert "test-agent" in response.body.decode()
    assert "/ui/assets/test_ui.css" in response.body.decode()
    assert "/ui/assets/test_ui.js" in response.body.decode()


@pytest.mark.asyncio
async def test_test_ui_run_calls_gateway() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    run = _test_ui_routes(_agent_card(), gateway)[1].endpoint

    response = await run(
        _request(
            "POST",
            "/ui/run",
            {
            "objective": "hello",
            "files": [
                {
                    "name": "note.txt",
                    "mime_type": "text/plain",
                    "content_base64": "bm90ZQ==",
                }
            ],
            },
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "events": [
            {"type": "progress", "text": "received:hello:1"},
            {
                "type": "completion",
                "text": "done",
                "artifacts": [
                    {
                        "name": "result.txt",
                        "mime_type": "text/plain",
                        "data_base64": "aGVsbG8=",
                    }
                ],
            },
        ]
    }


@pytest.mark.asyncio
async def test_test_ui_includes_telemetry_metadata() -> None:
    gateway = TelemetryUIGateway(llm=MagicMock(), settings=BaseSettings())
    run = _test_ui_routes(_agent_card(), gateway)[1].endpoint

    response = await run(_request("POST", "/ui/run", {"objective": "hello"}))

    assert response.status_code == 200
    events = json.loads(response.body)["events"]
    telemetry = events[-1]
    assert telemetry["type"] == "telemetry"
    assert telemetry["model"] == "test/model"
    assert telemetry["iterations"] == 2
    assert telemetry["tokens"] == {
        "prompt": 11,
        "completion": 7,
        "cached": 3,
        "total": 18,
    }
    assert telemetry["otel_attributes"]["gen_ai.usage.total_tokens"] == 18
    assert telemetry["otel_attributes"]["lughus.ui.tool_call_count"] == 0


@pytest.mark.asyncio
async def test_test_ui_streams_events() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    stream = _test_ui_routes(_agent_card(), gateway)[3].endpoint

    response = await stream(_request("POST", "/ui/stream", {"objective": "hello"}))

    assert response.status_code == 200
    body = b"".join([chunk async for chunk in response.body_iterator])
    events = [json.loads(line) for line in body.splitlines()]
    assert events == [
        {"type": "progress", "text": "received:hello:0"},
        {
            "type": "completion",
            "text": "done",
            "artifacts": [
                {
                    "name": "result.txt",
                    "mime_type": "text/plain",
                    "data_base64": "aGVsbG8=",
                }
            ],
        },
    ]


@pytest.mark.asyncio
async def test_test_ui_fetches_otel_trace_url() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    otel = _test_ui_routes(_agent_card(), gateway)[2].endpoint

    with patch("lughus.ui_server._fetch_otel_url") as fetch:
        fetch.return_value = {
            "url": "http://localhost:16686/api/traces/abc",
            "status_code": 200,
            "content_type": "application/json",
            "text": "{\"data\": []}",
            "json": {"data": []},
        }
        response = await otel(
            _request(
                "POST",
                "/ui/otel/traces",
                {"url": "http://localhost:16686/api/traces/abc"},
            )
        )

    assert response.status_code == 200
    payload = json.loads(response.body)
    assert payload["json"] == {"data": []}
    fetch.assert_called_once_with("http://localhost:16686/api/traces/abc")


@pytest.mark.asyncio
async def test_test_ui_rejects_invalid_otel_trace_url() -> None:
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    otel = _test_ui_routes(_agent_card(), gateway)[2].endpoint

    response = await otel(
        _request("POST", "/ui/otel/traces", {"url": "grpc://localhost:4317"})
    )

    assert response.status_code == 400
    assert "http(s)" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_test_ui_sanitizes_uploaded_file_name() -> None:
    class NameGateway(BaseGateway):
        async def handle(
            self,
            objective: str,
            files: list[tuple[bytes, str, str]],
        ) -> AsyncIterator[ProgressEvent | CompletionEvent]:
            yield CompletionEvent(text=files[0][2])

    gateway = NameGateway(llm=MagicMock(), settings=BaseSettings())
    run = _test_ui_routes(_agent_card(), gateway)[1].endpoint

    response = await run(
        _request(
            "POST",
            "/ui/run",
            {
                "objective": "hello",
                "files": [
                    {
                        "name": "../../note.txt",
                        "mime_type": "text/plain",
                        "content_base64": "bm90ZQ==",
                    }
                ],
            },
        )
    )

    assert response.status_code == 200
    assert json.loads(response.body)["events"][0]["text"] == "note.txt"


@pytest.mark.asyncio
async def test_test_ui_enforces_objective_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_OBJECTIVE_CHARS", "3")
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    run = _test_ui_routes(_agent_card(), gateway)[1].endpoint

    response = await run(_request("POST", "/ui/run", {"objective": "hello"}))

    assert response.status_code == 400
    assert "Objective exceeds" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_test_ui_enforces_artifact_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_ARTIFACT_BYTES", "1")
    gateway = UIGateway(llm=MagicMock(), settings=BaseSettings())
    run = _test_ui_routes(_agent_card(), gateway)[1].endpoint

    response = await run(_request("POST", "/ui/run", {"objective": "ok"}))

    assert response.status_code == 400
    assert "Artifact" in json.loads(response.body)["error"]


@pytest.mark.asyncio
async def test_bounded_in_memory_task_store_evicts_by_size() -> None:
    store = BoundedInMemoryTaskStore(ttl_seconds=None, max_tasks=2)
    tasks = [MagicMock(id=f"task-{index}") for index in range(3)]

    for task in tasks:
        await store.save(task)

    assert await store.get("task-0") is None
    assert await store.get("task-1") is tasks[1]
    assert await store.get("task-2") is tasks[2]


@pytest.mark.asyncio
async def test_bounded_in_memory_task_store_expires_by_ttl(monkeypatch) -> None:
    now = 100.0
    monkeypatch.setattr("lughus.server.time.monotonic", lambda: now)
    store = BoundedInMemoryTaskStore(ttl_seconds=10.0, max_tasks=None)
    task = MagicMock(id="task-ttl")

    await store.save(task)
    assert await store.get("task-ttl") is task

    now = 111.0
    assert await store.get("task-ttl") is None


@pytest.mark.asyncio
async def test_bounded_in_memory_task_store_refreshes_saved_task_order() -> None:
    store = BoundedInMemoryTaskStore(ttl_seconds=None, max_tasks=2)
    task_0 = MagicMock(id="task-0")
    task_1 = MagicMock(id="task-1")
    task_2 = MagicMock(id="task-2")

    await store.save(task_0)
    await store.save(task_1)
    await store.save(task_0)
    await store.save(task_2)

    assert await store.get("task-0") is task_0
    assert await store.get("task-1") is None
    assert await store.get("task-2") is task_2
