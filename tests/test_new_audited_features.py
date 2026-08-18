from __future__ import annotations

import asyncio
import os
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
        # Reset loaded flag to force reload
        import lughus.config
        from lughus.config import _ensure_dotenv

        lughus.config._DOTENV_LOADED = False

        _ensure_dotenv()
        assert os.environ.get("CUSTOM_ENV_VAR") == "audited_success"
    finally:
        os.chdir(cwd)
        monkeypatch.delenv("CUSTOM_ENV_VAR", raising=False)


@pytest.mark.asyncio
async def test_execution_runtime_loop_binding() -> None:
    from lughus.runtime import ExecutionRuntime

    runtime = ExecutionRuntime()
    assert runtime._loop is None
    # Access runtime inside active loop
    async with runtime.tool_slot():
        assert runtime._loop is not None
    await runtime.close()


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
async def test_stream_mid_stream_error_propagates() -> None:
    """W2-02: single retry layer lives at LLM.astream() level, not in the loop.

    Once streaming has begun and the first chunk is emitted, a mid-stream
    error propagates to the caller instead of silently retrying.
    """
    from lughus.loop import agent_loop_stream
    from lughus.testing import _make_streaming_chunk
    from lughus.tools import ToolRegistry

    class FaultyStreamingLLM:
        model = "test/mock-model"
        timeout = 1.0

        async def astream(self, *, messages, tools=None):
            async def faulty_iter():
                yield _make_streaming_chunk(content="Partial")
                raise TimeoutError("Simulated connection timeout during streaming")

            return faulty_iter()

    llm = FaultyStreamingLLM()
    registry = ToolRegistry()

    with pytest.raises(TimeoutError, match="Simulated connection timeout"):
        async for _ in agent_loop_stream(
            llm,
            system="You help.",
            context="Hi",
            registry=registry,
            tool_names=[],
            state=None,
        ):
            pass
