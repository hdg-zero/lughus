"""Base settings for lughus agents."""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)


_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        _DOTENV_LOADED = True
        try:
            from dotenv import load_dotenv

            dotenv_path = os.path.join(os.getcwd(), ".env")
            if os.path.exists(dotenv_path):
                load_dotenv(dotenv_path)
            else:
                load_dotenv()
        except ImportError:
            # Fallback to simple manual parsing if dotenv is not installed
            if os.path.exists(".env"):
                with open(".env", "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and os.getenv(k) is None:
                                os.environ[k] = v


def _env_int(key: str, default: int) -> int:
    _ensure_dotenv()
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        _logger.warning(
            "Invalid integer environment variable %s=%r; using default %r",
            key,
            value,
            default,
        )
        return default


def _env_float(key: str, default: float) -> float:
    _ensure_dotenv()
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        _logger.warning(
            "Invalid float environment variable %s=%r; using default %r",
            key,
            value,
            default,
        )
        return default


def _env_bool(key: str, default: bool) -> bool:
    _ensure_dotenv()
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BaseSettings:
    """Common configuration for all agents. Subclass to add agent-specific fields.

    All fields are read from environment variables **at instantiation time**
    (not at import time), making them compatible with ``pytest`` monkeypatching
    and ``python-dotenv`` loading patterns.

    The ``model`` field defaults to the ``AGENT_MODEL`` environment variable.
    If unset, the agent will fail at startup with a clear ``ValueError``.
    """

    model: str = field(default_factory=lambda: os.getenv("AGENT_MODEL", ""))
    max_output_tokens: int = field(default_factory=lambda: _env_int("MAX_OUTPUT_TOKENS", 16384))

    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", ""))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    environment: str = field(default_factory=lambda: os.getenv("LUGHUS_ENV", "development"))
    enable_test_ui: bool = field(default_factory=lambda: _env_bool("ENABLE_TEST_UI", False))
    api_bearer_token: str = field(default_factory=lambda: os.getenv("API_BEARER_TOKEN", ""))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))

    max_file_bytes: int = field(
        default_factory=lambda: _env_int("MAX_FILE_BYTES", 25 * 1024 * 1024)
    )
    max_files: int = field(default_factory=lambda: _env_int("MAX_FILES", 10))
    max_request_bytes: int = field(
        default_factory=lambda: _env_int("MAX_REQUEST_BYTES", 50 * 1024 * 1024)
    )
    max_http_body_bytes: int = field(
        default_factory=lambda: _env_int("MAX_HTTP_BODY_BYTES", 80 * 1024 * 1024)
    )
    max_objective_chars: int = field(
        default_factory=lambda: _env_int("MAX_OBJECTIVE_CHARS", 100_000)
    )
    max_source_chars: int = field(default_factory=lambda: _env_int("MAX_SOURCE_CHARS", 12_000))
    max_artifacts: int = field(default_factory=lambda: _env_int("MAX_ARTIFACTS", 10))
    max_artifact_bytes: int = field(
        default_factory=lambda: _env_int("MAX_ARTIFACT_BYTES", 50 * 1024 * 1024)
    )
    max_total_artifact_bytes: int = field(
        default_factory=lambda: _env_int("MAX_TOTAL_ARTIFACT_BYTES", 100 * 1024 * 1024)
    )

    # Maximum active HTTP requests handled by one ASGI app instance. Set to 0
    # to disable this framework-level backpressure guard. Env: MAX_CONCURRENT_REQUESTS.
    max_concurrent_requests: int = field(
        default_factory=lambda: _env_int("MAX_CONCURRENT_REQUESTS", 0)
    )

    # Maximum requests allowed to wait for a concurrency slot in one ASGI app
    # instance. Set to 0 to reject once all slots are active. Env: MAX_QUEUE_BACKLOG.
    max_queue_backlog: int = field(default_factory=lambda: _env_int("MAX_QUEUE_BACKLOG", 0))

    # How long a request waits for an available concurrency slot before the
    # server responds with 503. Set to 0 to fail immediately. Env: REQUEST_QUEUE_TIMEOUT.
    request_queue_timeout: float = field(
        default_factory=lambda: _env_float("REQUEST_QUEUE_TIMEOUT", 5.0)
    )

    # LLM call timeout in seconds. Set to 0 or a negative value to disable.
    # Increase for slow local models (e.g. Ollama). Env: LLM_TIMEOUT.
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 120.0))

    # Number of retries on transient LLM errors (RateLimitError, ServiceUnavailableError,
    # APIConnectionError). Set to 0 to disable retries. Env: LLM_MAX_RETRIES.
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 3))

    # Base delay in seconds for exponential backoff between retries.
    # Delay for attempt N is retry_base_delay * 2**N. Env: LLM_RETRY_BASE_DELAY.
    retry_base_delay: float = field(default_factory=lambda: _env_float("LLM_RETRY_BASE_DELAY", 1.0))

    # Total retry delay budget in seconds. Set to 0 or a negative value to disable.
    # Env: LLM_RETRY_MAX_ELAPSED.
    retry_max_elapsed: float = field(
        default_factory=lambda: _env_float("LLM_RETRY_MAX_ELAPSED", 0.0)
    )

    # Total agent timeout in seconds — applied to the entire handle() call in BaseGateway.
    # Set to 0 to disable. Env: AGENT_TIMEOUT.
    agent_timeout: float = field(default_factory=lambda: _env_float("AGENT_TIMEOUT", 600.0))

    # Bounds for the default in-process task store. Set TASK_STORE_TTL_SECONDS
    # to 0 to disable TTL expiry; set TASK_STORE_MAX_TASKS to 0 to disable
    # count-based eviction. Persistent stores should still be used for
    # horizontally scaled production deployments.
    task_store_ttl_seconds: float = field(
        default_factory=lambda: _env_float("TASK_STORE_TTL_SECONDS", 24 * 60 * 60)
    )
    task_store_max_tasks: int = field(
        default_factory=lambda: _env_int("TASK_STORE_MAX_TASKS", 10_000)
    )

    # Maximum number of tool calls to run concurrently inside one loop iteration.
    # Env: MAX_PARALLEL_TOOLS.
    max_parallel_tools: int = field(default_factory=lambda: _env_int("MAX_PARALLEL_TOOLS", 8))

    # Maximum number of tool calls to run concurrently in this event loop / worker.
    # Env: MAX_GLOBAL_TOOLS.
    max_global_tools: int = field(default_factory=lambda: _env_int("MAX_GLOBAL_TOOLS", 64))

    # Maximum worker threads used for synchronous tools and framework blocking
    # work. Env: MAX_SYNC_THREAD_WORKERS.
    max_sync_thread_workers: int = field(
        default_factory=lambda: _env_int("MAX_SYNC_THREAD_WORKERS", 32)
    )

    # Per-tool timeout in seconds. Set to 0 or a negative value to disable.
    # Env: TOOL_TIMEOUT.
    tool_timeout: float = field(default_factory=lambda: _env_float("TOOL_TIMEOUT", 120.0))

    # How long a tool waits for a worker-local global tool slot before returning
    # a structured timeout error. Set to 0 to fail immediately. Env: TOOL_QUEUE_TIMEOUT.
    tool_queue_timeout: float = field(
        default_factory=lambda: _env_float("TOOL_QUEUE_TIMEOUT", 30.0)
    )

    # Size limits that protect the LLM message history from tool payload blowups.
    # Env: MAX_TOOL_ARGS_CHARS / MAX_TOOL_OUTPUT_CHARS / COMPACT_TOOL_SCHEMAS.
    max_tool_args_chars: int = field(
        default_factory=lambda: _env_int("MAX_TOOL_ARGS_CHARS", 20_000)
    )
    max_tool_output_chars: int = field(
        default_factory=lambda: _env_int("MAX_TOOL_OUTPUT_CHARS", 20_000)
    )
    max_message_history_chars: int = field(
        default_factory=lambda: _env_int("MAX_MESSAGE_HISTORY_CHARS", 200_000)
    )
    compact_tool_schemas: bool = field(
        default_factory=lambda: _env_bool("COMPACT_TOOL_SCHEMAS", False)
    )
