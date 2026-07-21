"""Tests for BaseSettings — validates the import-time env eval fix (B3)."""

from __future__ import annotations

import os

import pytest

from lughus.config import BaseSettings, _env_int, _env_float, _env_bool
from lughus.loop._config import ToolExecutionConfig


# ── _env_int ──────────────────────────────────────────────────────────────────


def test_env_int_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_INT", "42")
    assert _env_int("TEST_INT", 0) == 42


def test_env_int_fallback_on_missing(monkeypatch) -> None:
    monkeypatch.delenv("TEST_INT", raising=False)
    assert _env_int("TEST_INT", 99) == 99


def test_env_int_fallback_on_invalid(monkeypatch) -> None:
    monkeypatch.setenv("TEST_INT", "not_a_number")
    with pytest.raises(ValueError, match="must be an integer"):
        _env_int("TEST_INT", 7)


# ── _env_float ────────────────────────────────────────────────────────────────


def test_env_float_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_FLOAT", "3.14")
    assert _env_float("TEST_FLOAT", 0.0) == pytest.approx(3.14)


def test_env_float_fallback_on_invalid(monkeypatch) -> None:
    monkeypatch.setenv("TEST_FLOAT", "oops")
    with pytest.raises(ValueError, match="must be a number"):
        _env_float("TEST_FLOAT", 1.5)


# ── BaseSettings — core fix (B3) ──────────────────────────────────────────────


def test_settings_reads_agent_model_at_instantiation(monkeypatch) -> None:
    """B3: env vars are read at instantiation, not at import time."""
    monkeypatch.setenv("AGENT_MODEL", "openai/gpt-4o")
    s = BaseSettings()
    assert s.model == "openai/gpt-4o"


def test_settings_model_changes_with_env(monkeypatch) -> None:
    """B3: two instances with different env values get different models."""
    monkeypatch.setenv("AGENT_MODEL", "model-a")
    s1 = BaseSettings()
    monkeypatch.setenv("AGENT_MODEL", "model-b")
    s2 = BaseSettings()
    assert s1.model == "model-a"
    assert s2.model == "model-b"


def test_settings_default_model_is_empty(monkeypatch) -> None:
    """When AGENT_MODEL is not set, model defaults to empty string."""
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    s = BaseSettings()
    assert s.model == ""


def test_settings_default_values(monkeypatch) -> None:
    """All default values match the documented defaults."""
    for key in (
        "AGENT_MODEL",
        "MAX_OUTPUT_TOKENS",
        "HOST",
        "PORT",
        "PUBLIC_URL",
        "LOG_LEVEL",
        "LUGHUS_ENV",
        "API_BEARER_TOKEN",
        "MAX_FILE_BYTES",
        "MAX_FILES",
        "MAX_REQUEST_BYTES",
        "MAX_HTTP_BODY_BYTES",
        "MAX_OBJECTIVE_CHARS",
        "MAX_ARTIFACTS",
        "MAX_ARTIFACT_BYTES",
        "MAX_TOTAL_ARTIFACT_BYTES",
        "MAX_CONCURRENT_REQUESTS",
        "MAX_QUEUE_BACKLOG",
        "REQUEST_QUEUE_TIMEOUT",
        "MAX_SOURCE_CHARS",
        "LLM_TIMEOUT",
        "MAX_PARALLEL_TOOLS",
        "TOOL_TIMEOUT",
        "MAX_GLOBAL_TOOLS",
        "MAX_SYNC_THREAD_WORKERS",
        "MAX_TOOL_ARGS_CHARS",
        "MAX_TOOL_OUTPUT_CHARS",
        "LLM_RETRY_MAX_ELAPSED",
        "TASK_STORE_TTL_SECONDS",
        "TASK_STORE_MAX_TASKS",
        "MAX_MESSAGE_HISTORY_CHARS",
    ):
        monkeypatch.delenv(key, raising=False)

    s = BaseSettings()
    assert s.model == ""
    assert s.max_output_tokens == 16384
    assert s.host == "0.0.0.0"
    assert s.port == 8080
    assert s.public_url == ""
    assert s.log_level == "INFO"
    assert s.environment == "development"
    assert s.api_bearer_token == ""
    assert s.max_file_bytes == 25 * 1024 * 1024
    assert s.max_files == 10
    assert s.max_request_bytes == 50 * 1024 * 1024
    assert s.max_http_body_bytes == 80 * 1024 * 1024
    assert s.max_objective_chars == 100_000
    assert s.max_source_chars == 12_000
    assert s.max_artifacts == 10
    assert s.max_artifact_bytes == 50 * 1024 * 1024
    assert s.max_total_artifact_bytes == 100 * 1024 * 1024
    assert s.max_concurrent_requests == 0
    assert s.max_queue_backlog == 0
    assert s.request_queue_timeout == pytest.approx(5.0)
    assert s.llm_timeout == pytest.approx(120.0)
    assert s.retry_max_elapsed == pytest.approx(0.0)
    assert s.task_store_ttl_seconds == pytest.approx(24 * 60 * 60)
    assert s.task_store_max_tasks == 10_000
    assert s.max_parallel_tools == 8
    assert s.max_global_tools == 64
    assert s.max_sync_thread_workers == 32
    assert s.tool_timeout == pytest.approx(120.0)
    assert s.tool_queue_timeout == pytest.approx(30.0)
    assert s.max_tool_args_chars == 20_000
    assert s.max_tool_output_chars == 20_000
    assert s.max_message_history_chars == 200_000
    assert s.compact_tool_schemas is False


def test_settings_custom_port(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9090")
    s = BaseSettings()
    assert s.port == 9090


def test_settings_invalid_port_fallback(monkeypatch) -> None:
    """Invalid int env var raises ValueError."""
    monkeypatch.setenv("PORT", "not_a_port")
    with pytest.raises(ValueError, match="must be an integer"):
        BaseSettings()


def test_settings_llm_timeout(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT", "60.0")
    monkeypatch.setenv("LLM_RETRY_MAX_ELAPSED", "3.5")
    s = BaseSettings()
    assert s.llm_timeout == pytest.approx(60.0)
    assert s.retry_max_elapsed == pytest.approx(3.5)


def test_settings_file_limits(monkeypatch) -> None:
    monkeypatch.setenv("MAX_FILE_BYTES", "512")
    monkeypatch.setenv("MAX_FILES", "4")
    monkeypatch.setenv("MAX_REQUEST_BYTES", "1024")
    monkeypatch.setenv("MAX_HTTP_BODY_BYTES", "2048")
    monkeypatch.setenv("MAX_OBJECTIVE_CHARS", "128")
    monkeypatch.setenv("MAX_ARTIFACTS", "2")
    monkeypatch.setenv("MAX_ARTIFACT_BYTES", "4096")
    monkeypatch.setenv("MAX_TOTAL_ARTIFACT_BYTES", "8192")
    monkeypatch.setenv("MAX_CONCURRENT_REQUESTS", "12")
    monkeypatch.setenv("MAX_QUEUE_BACKLOG", "3")
    monkeypatch.setenv("REQUEST_QUEUE_TIMEOUT", "0.25")
    s = BaseSettings()
    assert s.max_files == 4
    assert s.max_request_bytes == 1024
    assert s.max_http_body_bytes == 2048
    assert s.max_objective_chars == 128
    assert s.max_artifacts == 2
    assert s.max_artifact_bytes == 4096
    assert s.max_total_artifact_bytes == 8192
    assert s.max_concurrent_requests == 12
    assert s.max_queue_backlog == 3
    assert s.request_queue_timeout == pytest.approx(0.25)


def test_settings_tool_execution_limits(monkeypatch) -> None:
    monkeypatch.setenv("MAX_PARALLEL_TOOLS", "3")
    monkeypatch.setenv("MAX_GLOBAL_TOOLS", "9")
    monkeypatch.setenv("MAX_SYNC_THREAD_WORKERS", "5")
    monkeypatch.setenv("TOOL_TIMEOUT", "10.5")
    monkeypatch.setenv("TOOL_QUEUE_TIMEOUT", "2.5")
    monkeypatch.setenv("MAX_TOOL_ARGS_CHARS", "100")
    monkeypatch.setenv("MAX_TOOL_OUTPUT_CHARS", "200")
    monkeypatch.setenv("MAX_MESSAGE_HISTORY_CHARS", "300")
    monkeypatch.setenv("COMPACT_TOOL_SCHEMAS", "true")
    s = BaseSettings()
    assert s.max_parallel_tools == 3
    assert s.max_global_tools == 9
    assert s.max_sync_thread_workers == 5
    assert s.tool_timeout == pytest.approx(10.5)
    assert s.tool_queue_timeout == pytest.approx(2.5)
    assert s.max_tool_args_chars == 100
    assert s.max_tool_output_chars == 200
    assert s.max_message_history_chars == 300
    assert s.compact_tool_schemas is True


def test_settings_subclass(monkeypatch) -> None:
    """Subclasses with custom fields work correctly."""
    from dataclasses import dataclass, field

    @dataclass(frozen=True)
    class MySettings(BaseSettings):
        my_api_key: str = field(default_factory=lambda: os.getenv("MY_API_KEY", "default-key"))

    monkeypatch.setenv("AGENT_MODEL", "test/model")
    monkeypatch.setenv("MY_API_KEY", "sk-custom-123")
    s = MySettings()
    assert s.model == "test/model"
    assert s.my_api_key == "sk-custom-123"


def test_settings_frozen(monkeypatch) -> None:
    """BaseSettings is immutable (frozen dataclass)."""
    monkeypatch.setenv("AGENT_MODEL", "test/model")
    s = BaseSettings()
    with pytest.raises((AttributeError, TypeError)):
        s.model = "other"  # type: ignore[misc]


# ── _env_bool ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("val", ("1", "true", "yes", "on", "TRUE", "  Yes  "))
def test_env_bool_true_values(monkeypatch, val: str) -> None:
    monkeypatch.setenv("TEST_BOOL", val)
    assert _env_bool("TEST_BOOL", False) is True


@pytest.mark.parametrize("val", ("0", "false", "no", "off", "OFF"))
def test_env_bool_false_values(monkeypatch, val: str) -> None:
    monkeypatch.setenv("TEST_BOOL", val)
    assert _env_bool("TEST_BOOL", True) is False


def test_env_bool_fallback_on_missing(monkeypatch) -> None:
    monkeypatch.delenv("TEST_BOOL", raising=False)
    assert _env_bool("TEST_BOOL", True) is True


@pytest.mark.parametrize("val", ("ture", "yess", "2", "oui", ""))
def test_env_bool_rejects_unknown(monkeypatch, val: str) -> None:
    monkeypatch.setenv("TEST_BOOL", val)
    with pytest.raises(ValueError):
        _env_bool("TEST_BOOL", False)


# ── BaseSettings Validation ───────────────────────────────────────────────────


def test_settings_rejects_zero_positive_field() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        BaseSettings(max_files=0)


def test_settings_rejects_negative_positive_field() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        BaseSettings(max_parallel_tools=-1)


def test_settings_rejects_multiple_invalid_fields() -> None:
    with pytest.raises(ValueError) as exc_info:
        BaseSettings(max_files=0, max_artifacts=-1)
    msg = str(exc_info.value)
    assert "max_artifacts" in msg
    assert "max_files" in msg


def test_settings_rejects_file_bytes_exceeding_request() -> None:
    with pytest.raises(ValueError, match="cannot exceed MAX_REQUEST_BYTES"):
        BaseSettings(max_file_bytes=100, max_request_bytes=50)


def test_settings_rejects_request_exceeding_body() -> None:
    with pytest.raises(ValueError, match="cannot exceed MAX_HTTP_BODY_BYTES"):
        BaseSettings(max_file_bytes=50, max_request_bytes=100, max_http_body_bytes=50)


def test_settings_rejects_port_zero() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        BaseSettings(port=0)


def test_settings_rejects_port_out_of_range() -> None:
    with pytest.raises(ValueError, match="PORT must be between"):
        BaseSettings(port=70000)


def test_settings_rejects_empty_model_in_production(monkeypatch) -> None:
    monkeypatch.setenv("LUGHUS_ENV", "production")
    with pytest.raises(ValueError, match="AGENT_MODEL must be set in production"):
        BaseSettings(model="", environment="production")


def test_settings_allows_empty_model_in_development(monkeypatch) -> None:
    monkeypatch.setenv("LUGHUS_ENV", "development")
    s = BaseSettings(model="", environment="development")
    assert s.model == ""


def test_settings_rejects_negative_timeout() -> None:
    with pytest.raises(ValueError, match="must be non-negative"):
        BaseSettings(llm_timeout=-1.0)


def test_settings_allows_zero_timeout() -> None:
    s = BaseSettings(llm_timeout=0.0)
    assert s.llm_timeout == 0.0


def test_settings_reads_cors_allow_credentials(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    s = BaseSettings()
    assert s.cors_allow_credentials is True


# ── ToolExecutionConfig ───────────────────────────────────────────────────────


def test_tool_config_rejects_zero() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ToolExecutionConfig(max_parallel_tools=0)


def test_tool_config_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        ToolExecutionConfig(max_global_tools=-1)
