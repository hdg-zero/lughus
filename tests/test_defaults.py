"""Assert tightened defaults value-by-value.

Every variable-backed default MUST be tested with the env var cleared
(monkeypatch.delenv) so the test validates the fallback, not the env.
"""

from __future__ import annotations

import pytest

from lughus.loop._config import (
    DEFAULT_MAX_GLOBAL_TOOLS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_MESSAGE_HISTORY_CHARS,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DEFAULT_MAX_SYNC_THREAD_WORKERS,
    DEFAULT_MAX_TOOL_ARGS_CHARS,
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    DEFAULT_TOOL_QUEUE_TIMEOUT,
    ToolExecutionConfig,
)


def test_default_max_iterations() -> None:
    assert DEFAULT_MAX_ITERATIONS == 12


def test_default_max_parallel_tools() -> None:
    assert DEFAULT_MAX_PARALLEL_TOOLS == 4


def test_default_tool_timeout() -> None:
    cfg = ToolExecutionConfig()
    assert cfg.tool_timeout == pytest.approx(30.0)


def test_default_max_tool_output_chars() -> None:
    assert DEFAULT_MAX_TOOL_OUTPUT_CHARS == 8_192


def test_default_max_tool_args_chars() -> None:
    assert DEFAULT_MAX_TOOL_ARGS_CHARS == 20_000


def test_default_max_global_tools() -> None:
    assert DEFAULT_MAX_GLOBAL_TOOLS == 64


def test_default_max_sync_thread_workers() -> None:
    assert DEFAULT_MAX_SYNC_THREAD_WORKERS == 32


def test_default_max_message_history_chars() -> None:
    assert DEFAULT_MAX_MESSAGE_HISTORY_CHARS == 200_000


def test_default_tool_queue_timeout() -> None:
    assert pytest.approx(30.0) == DEFAULT_TOOL_QUEUE_TIMEOUT


def test_tool_config_uses_tightened_defaults() -> None:
    """ToolExecutionConfig reflects all tightened module-level constants."""
    cfg = ToolExecutionConfig()
    assert cfg.max_parallel_tools == 4
    assert cfg.tool_timeout == pytest.approx(30.0)
    assert cfg.max_tool_output_chars == 8_192
    assert cfg.max_tool_args_chars == 20_000
    assert cfg.max_message_history_chars == 200_000


def test_base_settings_tightened_defaults(monkeypatch) -> None:
    """BaseSettings env-backed defaults match the tightened values."""
    for key in (
        "MAX_PARALLEL_TOOLS",
        "TOOL_TIMEOUT",
        "MAX_TOOL_OUTPUT_CHARS",
        "MAX_TOOL_ARGS_CHARS",
        "MAX_MESSAGE_HISTORY_CHARS",
        "MAX_GLOBAL_TOOLS",
        "MAX_SYNC_THREAD_WORKERS",
        "TOOL_QUEUE_TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)

    from lughus.config import BaseSettings

    s = BaseSettings()
    assert s.max_parallel_tools == 4
    assert s.tool_timeout == pytest.approx(30.0)
    assert s.max_tool_output_chars == 8_192
