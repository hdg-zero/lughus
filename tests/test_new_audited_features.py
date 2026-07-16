from __future__ import annotations

import os
import asyncio
from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient

from lughus import BaseSettings, build_app
from lughus.gateway import BaseGateway
from lughus.ui_server import _is_safe_otel_url


class SimpleGateway(BaseGateway):
    async def handle(self, objective, files):
        yield


def test_cors_middleware_integration() -> None:
    settings = BaseSettings(cors_origins="http://example.com,https://test.com")
    gateway = SimpleGateway(llm=MagicMock(), settings=settings)
    app = build_app(MagicMock(name="test"), gateway, setup_otel=False)
    client = TestClient(app)

    # Preflight OPTIONS request
    response = client.options(
        "/health",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://example.com"
    assert "GET" in response.headers.get("access-control-allow-methods", "")


def test_timing_safe_multi_key_auth() -> None:
    settings = BaseSettings(api_bearer_token="key1,key2", environment="development")
    gateway = SimpleGateway(llm=MagicMock(), settings=settings)
    app = build_app(MagicMock(name="test"), gateway, setup_otel=False)
    client = TestClient(app)

    # Health check is exempt
    resp = client.get("/health")
    assert resp.status_code == 200

    # Call main endpoint (e.g. POST /) which is JSON-RPC
    # Unauthorized
    resp = client.post("/", headers={"Authorization": "Bearer bad"})
    assert resp.status_code == 401

    # Authorized with key1
    resp = client.post("/", headers={"Authorization": "Bearer key1"}, json={})
    assert resp.status_code != 401

    # Authorized with key2
    resp = client.post("/", headers={"Authorization": "Bearer key2"}, json={})
    assert resp.status_code != 401


def test_ssrf_proxy_protection(monkeypatch) -> None:
    # 127.0.0.1 and localhost should be safe by default
    assert _is_safe_otel_url("http://127.0.0.1:16686/api/traces/abc") is True
    assert _is_safe_otel_url("http://localhost:16686/api/traces/abc") is True

    # Private IP addresses must be blocked
    assert _is_safe_otel_url("http://192.168.1.50:16686/api/traces/abc") is False
    assert _is_safe_otel_url("http://10.0.0.1:16686/api/traces/abc") is False
    assert _is_safe_otel_url("http://172.16.5.5:16686/api/traces/abc") is False

    # Whitelisted hosts via environment variable
    monkeypatch.setenv("LUGHUS_ALLOWED_OTEL_HOSTS", "otel-collector,internal-jaeger")
    assert _is_safe_otel_url("http://otel-collector:16686/api/traces/abc") is True
    assert _is_safe_otel_url("http://internal-jaeger:16686/api/traces/abc") is True
    assert _is_safe_otel_url("http://other-internal:16686/api/traces/abc") is False


@pytest.mark.asyncio
async def test_gateway_graceful_shutdown() -> None:
    gateway = SimpleGateway(llm=MagicMock(), settings=BaseSettings())
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    gateway._running_tasks["task-1"] = future

    await gateway.shutdown()
    assert future.cancelled()
    assert "task-1" in gateway._running_tasks  # cleanup happens in execute() finally block


def test_ensure_dotenv_loads_file(tmp_path, monkeypatch) -> None:
    # Write a temporary .env file
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("CUSTOM_ENV_VAR=audited_success\n", encoding="utf-8")

    # Change working directory temporarily to read the file
    cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path))
        from lughus.config import _ensure_dotenv

        # Reset loaded flag to force reload
        import lughus.config

        lughus.config._DOTENV_LOADED = False

        _ensure_dotenv()
        assert os.environ.get("CUSTOM_ENV_VAR") == "audited_success"
    finally:
        os.chdir(cwd)
        monkeypatch.delenv("CUSTOM_ENV_VAR", raising=False)


def test_event_loop_weakref_no_leak() -> None:
    import gc
    from lughus._threading import _get_sync_semaphore, _SYNC_SEMAPHORES

    class FakeLoop:
        pass

    loop = FakeLoop()
    sem = _get_sync_semaphore(loop, 10)
    assert sem is not None

    # Check that it exists in semaphores
    keys = list(_SYNC_SEMAPHORES.keys())
    assert any(k[0]() is loop for k in keys)

    # Delete loop and collect
    del loop
    gc.collect()

    # Access with another loop to trigger cleanup
    loop2 = FakeLoop()
    _get_sync_semaphore(loop2, 5)

    # Check that the first loop was cleaned up
    keys2 = list(_SYNC_SEMAPHORES.keys())
    assert not any(k[0]() is None for k in keys2)


def test_resolve_and_validate_otel_url(monkeypatch) -> None:
    import socket
    from lughus.ui_server import _resolve_and_validate_otel_url

    # Mock resolution to a private IP
    def mock_getaddrinfo_private(host, port):
        return [(None, None, None, None, ("192.168.1.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo_private)

    with pytest.raises(ValueError, match="not allowed"):
        _resolve_and_validate_otel_url("http://attacker-rebinding.com/api/traces")

    # Mock resolution to a safe IP
    def mock_getaddrinfo_safe(host, port):
        return [(None, None, None, None, ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo_safe)

    rewritten, host = _resolve_and_validate_otel_url("http://my-host:16686/api/traces")
    assert rewritten == "http://127.0.0.1:16686/api/traces"
    assert host == "my-host"


@pytest.mark.asyncio
async def test_stream_retry_on_transient_error() -> None:
    from lughus.loop import agent_loop_stream
    from lughus.testing import _make_streaming_chunk, _make_streaming_text_response
    from lughus.tools import ToolRegistry

    class FaultyStreamingLLM:
        model = "test/mock-model"
        timeout = 1.0
        max_retries = 2
        retry_base_delay = 0.01
        retry_max_elapsed = None

        def __init__(self):
            self.calls = 0

        async def astream(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:

                async def faulty_iter():
                    yield _make_streaming_chunk(content="Partial")
                    raise TimeoutError("Simulated connection timeout during streaming")

                return faulty_iter()
            else:
                return _make_streaming_text_response("Hello Success")

    llm = FaultyStreamingLLM()
    registry = ToolRegistry()
    chunks = []

    async for chunk in agent_loop_stream(
        llm,
        system="You help.",
        context="Hi",
        registry=registry,
        tool_names=[],
        state=None,
    ):
        chunks.append(chunk)

    # First stream fails, retry succeeds: it should yield "Hello Success" from the second attempt
    assert len(chunks) >= 2
    assert "Hello" in str(chunks[-1])
    assert chunks[-1].iterations == 1
    assert llm.calls == 2
