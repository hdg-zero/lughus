"""Base settings for lughus agents."""

from __future__ import annotations

import contextlib
import contextvars
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from ..core._defaults import (
    DEFAULT_MAX_GLOBAL_TOOLS,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DEFAULT_MAX_SYNC_THREAD_WORKERS,
    DEFAULT_MAX_TOOL_ARGS_CHARS,
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    DEFAULT_TOOL_QUEUE_TIMEOUT,
)

__all__ = ["BaseSettings", "isolated_env"]


_DOTENV_LOADED = False
_current_env: contextvars.ContextVar[Mapping[str, str] | None] = contextvars.ContextVar(
    "_current_env", default=None
)


@contextlib.contextmanager
def isolated_env(env: Mapping[str, str] | None = None) -> Iterator[None]:
    """Temporarily scope environment variable lookups without mutating os.environ."""
    token = _current_env.set({} if env is None else env)
    try:
        yield
    finally:
        _current_env.reset(token)


def _ensure_dotenv() -> None:
    global _DOTENV_LOADED
    if not _DOTENV_LOADED:
        _DOTENV_LOADED = True
        try:
            from dotenv import load_dotenv

            path = os.path.join(os.getcwd(), ".env")
            load_dotenv(path if os.path.exists(path) else None)
        except ImportError:
            if os.path.exists(".env"):
                with open(".env", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            k, v = line.split("=", 1)
                            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def _get_raw_env(key: str) -> str | None:
    scoped = _current_env.get()
    if scoped is not None:
        return scoped.get(key)
    _ensure_dotenv()
    return os.getenv(key)


def _getenv(key: str, default: str = "") -> str:
    """os.getenv, but guarantees the .env file is loaded first."""
    val = _get_raw_env(key)
    return default if val is None else val


def _env_int(key: str, default: int) -> int:
    val = _get_raw_env(key)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer, got {val!r}") from exc


def _env_float(key: str, default: float) -> float:
    val = _get_raw_env(key)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number, got {val!r}") from exc


def _env_bool(key: str, default: bool) -> bool:
    val = _get_raw_env(key)
    if val is None:
        return default
    normalized = val.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean, got {val!r}")


_POSITIVE_FIELDS = (
    "port",
    "max_output_tokens",
    "max_file_bytes",
    "max_files",
    "max_request_bytes",
    "max_http_body_bytes",
    "max_objective_chars",
    "max_artifacts",
    "max_artifact_bytes",
    "max_total_artifact_bytes",
    "max_parallel_tools",
    "max_global_tools",
    "max_sync_thread_workers",
    "max_tool_args_chars",
    "max_tool_output_chars",
)

_NON_NEGATIVE_FIELDS = (
    "max_concurrent_requests",
    "max_queue_backlog",
    "max_retries",
    "request_queue_timeout",
    "llm_timeout",
    "tool_timeout",
    "tool_queue_timeout",
    "agent_timeout",
    "retry_base_delay",
    "retry_max_elapsed",
    "task_store_ttl_seconds",
    "task_store_max_tasks",
)


@dataclass(frozen=True)
class BaseSettings:
    """Common configuration for all agents. Subclass to add agent-specific fields.

    All fields are read from environment variables **at instantiation time**
    (not at import time), making them compatible with ``pytest`` monkeypatching
    and ``python-dotenv`` loading patterns.

    The ``model`` field defaults to the ``AGENT_MODEL`` environment variable.
    If unset, the agent will fail at startup with a clear ``ValueError``.
    """

    model: str = field(default_factory=lambda: _getenv("AGENT_MODEL"))
    max_output_tokens: int = field(default_factory=lambda: _env_int("MAX_OUTPUT_TOKENS", 16384))

    host: str = field(default_factory=lambda: _getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8080))
    public_url: str = field(default_factory=lambda: _getenv("PUBLIC_URL"))
    log_level: str = field(default_factory=lambda: _getenv("LOG_LEVEL", "INFO"))
    environment: str = field(default_factory=lambda: _getenv("LUGHUS_ENV", "development"))
    enable_console: bool = field(default_factory=lambda: _env_bool("ENABLE_CONSOLE", False))
    api_bearer_token: str = field(default_factory=lambda: _getenv("API_BEARER_TOKEN"))
    cors_origins: str = field(default_factory=lambda: _getenv("CORS_ORIGINS"))

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
        default_factory=lambda: _env_float("LLM_RETRY_MAX_ELAPSED", 60.0)
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
    max_parallel_tools: int = field(
        default_factory=lambda: _env_int("MAX_PARALLEL_TOOLS", DEFAULT_MAX_PARALLEL_TOOLS)
    )

    # Maximum number of tool calls to run concurrently in this event loop / worker.
    # Env: MAX_GLOBAL_TOOLS.
    max_global_tools: int = field(
        default_factory=lambda: _env_int("MAX_GLOBAL_TOOLS", DEFAULT_MAX_GLOBAL_TOOLS)
    )

    # Maximum worker threads used for synchronous tools and framework blocking
    # work. Env: MAX_SYNC_THREAD_WORKERS.
    max_sync_thread_workers: int = field(
        default_factory=lambda: _env_int("MAX_SYNC_THREAD_WORKERS", DEFAULT_MAX_SYNC_THREAD_WORKERS)
    )

    # Per-tool timeout in seconds. Set to 0 or a negative value to disable.
    # Env: TOOL_TIMEOUT.
    tool_timeout: float = field(default_factory=lambda: _env_float("TOOL_TIMEOUT", 30.0))

    # How long a tool waits for a worker-local global tool slot before returning
    # a structured timeout error. Set to 0 to fail immediately. Env: TOOL_QUEUE_TIMEOUT.
    tool_queue_timeout: float = field(
        default_factory=lambda: _env_float("TOOL_QUEUE_TIMEOUT", DEFAULT_TOOL_QUEUE_TIMEOUT)
    )

    # Size limits that protect the LLM message history from tool payload blowups.
    # Env: MAX_TOOL_ARGS_CHARS / MAX_TOOL_OUTPUT_CHARS.
    max_tool_args_chars: int = field(
        default_factory=lambda: _env_int("MAX_TOOL_ARGS_CHARS", DEFAULT_MAX_TOOL_ARGS_CHARS)
    )
    max_tool_output_chars: int = field(
        default_factory=lambda: _env_int("MAX_TOOL_OUTPUT_CHARS", DEFAULT_MAX_TOOL_OUTPUT_CHARS)
    )
    cors_allow_credentials: bool = field(
        default_factory=lambda: _env_bool("CORS_ALLOW_CREDENTIALS", False)
    )

    def __post_init__(self) -> None:
        if isinstance(self.port, str):
            with contextlib.suppress(ValueError):
                object.__setattr__(self, "port", int(self.port))
        invalid = [name for name in _POSITIVE_FIELDS if getattr(self, name) <= 0]
        if invalid:
            raise ValueError(f"Settings must be positive: {', '.join(sorted(invalid))}")
        neg = [name for name in _NON_NEGATIVE_FIELDS if getattr(self, name) < 0]
        if neg:
            raise ValueError(f"Settings must be non-negative: {', '.join(sorted(neg))}")
        if not 1 <= self.port <= 65535:
            raise ValueError("PORT must be between 1 and 65535")
        if self.max_file_bytes > self.max_request_bytes:
            raise ValueError("MAX_FILE_BYTES cannot exceed MAX_REQUEST_BYTES")
        if self.max_request_bytes > self.max_http_body_bytes:
            raise ValueError("MAX_REQUEST_BYTES cannot exceed MAX_HTTP_BODY_BYTES")
        if self.environment.strip().lower() == "production" and not self.model:
            raise ValueError("AGENT_MODEL must be set in production")
