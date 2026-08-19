"""Tool result contract — uniform JSON envelope, retryable mapping,
truncation declaration, and anti-leak protection.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

import pytest

from lughus import ToolRegistry
from lughus.errors import (
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from lughus.loop import ToolExecutionConfig
from lughus.loop import _execute_tools as _raw_execute_tools
from lughus.loop._execute import _error_payload, _success_payload
from lughus.runtime import ExecutionRuntime, RuntimeConfig

# ── helpers ──────────────────────────────────────────────────────────


def _test_runtime(max_workers: int = 32) -> ExecutionRuntime:
    return ExecutionRuntime(RuntimeConfig(max_sync_workers=max_workers))


async def _execute_tools(
    tool_calls: list[tuple[str, str, str]],
    registry: ToolRegistry,
    state: Any = None,
    config: ToolExecutionConfig | None = None,
) -> list[tuple[str, str]]:
    runtime_to_close: ExecutionRuntime | None = None
    if config is None:
        runtime_to_close = _test_runtime()
        config = ToolExecutionConfig(runtime=runtime_to_close)
    elif config.runtime is None:
        runtime_to_close = _test_runtime()
        config = dataclasses.replace(config, runtime=runtime_to_close)
    try:
        return await _raw_execute_tools(tool_calls, registry, state, config=config)
    finally:
        if runtime_to_close is not None:
            await runtime_to_close.close()


_PATH_RE = re.compile(r"(?:[A-Za-z]:[/\\]|[/\\])[\w.\-]+(?:[/\\][\w.\-]+)+")


# ── 1. Every tool output is valid JSON with expected keys ────────────


@pytest.mark.asyncio
async def test_success_output_is_valid_json_with_expected_keys() -> None:
    """A successful tool result is valid JSON containing 'ok' and 'result'."""
    registry = ToolRegistry()

    @registry.tool(
        "echo",
        "Echo input.",
        {
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )
    def echo(*, msg: str, state: Any) -> str:
        return json.dumps({"echo": msg})

    results = await _execute_tools(
        [("call_1", "echo", '{"msg": "hello"}')],
        registry,
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is True
    assert "result" in data
    assert data["result"] == {"echo": "hello"}


@pytest.mark.asyncio
async def test_error_output_is_valid_json_with_expected_keys() -> None:
    """An error tool result is valid JSON with all required envelope keys."""
    registry = ToolRegistry()

    @registry.tool("boom", "Always fails.", {"type": "object", "properties": {}})
    def boom(*, state: Any) -> str:
        raise RuntimeError("kaboom")

    results = await _execute_tools(
        [("call_2", "boom", "{}")],
        registry,
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is False
    for key in ("error", "message", "retryable", "fix"):
        assert key in data, f"Missing key '{key}' in error envelope"


@pytest.mark.asyncio
async def test_unknown_tool_produces_valid_error_envelope() -> None:
    """An unknown tool name produces a valid error envelope."""
    registry = ToolRegistry()
    results = await _execute_tools(
        [("call_3", "nonexistent", "{}")],
        registry,
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is False
    assert data["error"] == "ToolValidationError"
    assert "nonexistent" in data["message"]
    assert isinstance(data["retryable"], bool)
    assert isinstance(data["fix"], str)


@pytest.mark.asyncio
async def test_success_with_non_json_output() -> None:
    """A tool returning plain text is wrapped in the success envelope."""
    registry = ToolRegistry()

    @registry.tool("plain", "Returns text.", {"type": "object", "properties": {}})
    def plain(*, state: Any) -> str:
        return "just text"

    results = await _execute_tools(
        [("call_4", "plain", "{}")],
        registry,
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is True
    assert data["result"] == "just text"


# ── 2. Truncated output carries truncated=True and original_bytes ────


@pytest.mark.asyncio
async def test_truncated_output_has_truncation_metadata() -> None:
    """When output exceeds max_tool_output_chars, the envelope declares truncation."""
    registry = ToolRegistry()

    @registry.tool("verbose", "Big output.", {"type": "object", "properties": {}})
    def verbose(*, state: Any) -> str:
        return "A" * 200

    results = await _execute_tools(
        [("call_trunc", "verbose", "{}")],
        registry,
        config=ToolExecutionConfig(max_tool_output_chars=50, runtime=_test_runtime()),
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is True
    assert data["truncated"] is True
    assert data["original_bytes"] == 200
    assert data["result"] == "A" * 50


@pytest.mark.asyncio
async def test_non_truncated_output_has_no_truncation_keys() -> None:
    """Normal-sized output does not carry truncation metadata."""
    registry = ToolRegistry()

    @registry.tool("small", "Small output.", {"type": "object", "properties": {}})
    def small(*, state: Any) -> str:
        return json.dumps({"x": 1})

    results = await _execute_tools(
        [("call_no_trunc", "small", "{}")],
        registry,
    )
    _, output = results[0]
    data = json.loads(output)
    assert data["ok"] is True
    assert "truncated" not in data
    assert "original_bytes" not in data


# ── 3. Exception-to-retryable mapping ───────────────────────────────


def test_tool_validation_error_is_retryable() -> None:
    """ToolValidationError maps to retryable=True with correct fix hint."""
    exc = ToolValidationError("Bad args")
    payload = json.loads(_error_payload(exc))
    assert payload["ok"] is False
    assert payload["retryable"] is True
    assert payload["fix"] == "Correct the arguments and retry"


def test_tool_timeout_error_is_retryable() -> None:
    """ToolTimeoutError maps to retryable=True with correct fix hint."""
    exc = ToolTimeoutError("Tool timed out")
    payload = json.loads(_error_payload(exc))
    assert payload["ok"] is False
    assert payload["retryable"] is True
    assert payload["fix"] == "Retry with simpler input or increase timeout"


def test_tool_execution_error_is_not_retryable() -> None:
    """Generic ToolExecutionError maps to retryable=False."""
    exc = ToolExecutionError("Something broke")
    payload = json.loads(_error_payload(exc))
    assert payload["ok"] is False
    assert payload["retryable"] is False
    assert payload["fix"] == "Try an alternative approach"


def test_unknown_exception_is_not_retryable() -> None:
    """An unknown exception type maps to retryable=False."""
    exc = Exception("mysterious failure")
    payload = json.loads(_error_payload(exc))
    assert payload["ok"] is False
    assert payload["retryable"] is False
    assert payload["fix"] == "Report the error to the user"


def test_safe_tool_error_retryable_propagated() -> None:
    """SafeToolError's own retryable flag is propagated."""
    exc_retry = SafeToolError("RATE_LIMIT", "Try later", retryable=True)
    payload_retry = json.loads(_error_payload(exc_retry))
    assert payload_retry["retryable"] is True
    assert payload_retry["fix"] == "Retry the operation"

    exc_no = SafeToolError("FATAL", "Cannot recover", retryable=False)
    payload_no = json.loads(_error_payload(exc_no))
    assert payload_no["retryable"] is False
    assert payload_no["fix"] == "Try an alternative approach"


def test_retryable_property_on_error_classes() -> None:
    """Error classes expose retryable as a class-level attribute."""
    assert ToolValidationError.retryable is True
    assert ToolExecutionError.retryable is False
    assert ToolTimeoutError.retryable is True

    # Instance-level for SafeToolError
    safe = SafeToolError("X", "msg", retryable=True)
    assert safe.retryable is True


# ── 4. Anti-leak protection ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_anti_leak_deep_stack_trace() -> None:
    """A tool raising with a deep stack trace leaks no internal info."""
    registry = ToolRegistry()

    @registry.tool("leaky", "Fails deep.", {"type": "object", "properties": {}})
    def leaky(*, state: Any) -> str:
        def level_1() -> str:
            def level_2() -> str:
                def level_3() -> str:
                    raise RuntimeError(
                        "Traceback (most recent call last):\n"
                        '  File "/home/user/lughus/loop/_execute.py", line 42\n'
                        "KeyError: 'secret_key'"
                    )

                return level_3()

            return level_2()

        return level_1()

    results = await _execute_tools(
        [("call_leak", "leaky", "{}")],
        registry,
    )
    _, output = results[0]

    # The entire output string must not contain leaked info
    assert "Traceback" not in output
    assert "lughus/" not in output
    assert "/home/" not in output
    assert "secret_key" not in output

    data = json.loads(output)
    assert data["ok"] is False
    assert data["message"] == "Tool execution failed"


def test_anti_leak_sanitizes_paths_in_safe_error() -> None:
    """Even SafeToolError messages have file paths redacted."""
    exc = SafeToolError(
        "FILE_ERR",
        "Cannot open /home/user/data/secret.csv for reading",
    )
    payload = json.loads(_error_payload(exc))
    assert "/home/" not in payload["message"]
    assert "secret.csv" not in payload["message"]


def test_anti_leak_sanitizes_lughus_references() -> None:
    """Internal 'lughus.' and 'lughus/' references are scrubbed."""
    exc = ToolValidationError("Error in lughus.loop._execute: schema mismatch")
    payload = json.loads(_error_payload(exc))
    assert "lughus." not in payload["message"]
    assert "lughus/" not in payload["message"]


def test_anti_leak_traceback_keyword_stripped() -> None:
    """The word 'Traceback' and everything after it is removed."""
    exc = ToolValidationError("Validation failed. Traceback (most recent call last): ...")
    payload = json.loads(_error_payload(exc))
    assert "Traceback" not in payload["message"]
    assert payload["message"] == "Validation failed."


def test_anti_leak_no_path_in_any_error_field() -> None:
    """No field in the error envelope contains a filesystem path."""
    exc = ToolTimeoutError("Tool 'db' at /opt/tools/db timed out after 30s")
    payload = json.loads(_error_payload(exc))
    serialized = json.dumps(payload)
    assert not _PATH_RE.search(serialized), f"Path pattern found in error envelope: {serialized}"


# ── 5. success_payload unit tests ───────────────────────────────────


def test_success_payload_parses_json_result() -> None:
    """_success_payload embeds parsed JSON as a native object."""
    result = json.loads(_success_payload('{"key": "val"}'))
    assert result == {"ok": True, "result": {"key": "val"}}


def test_success_payload_embeds_plain_text() -> None:
    """_success_payload embeds non-JSON text as a string."""
    result = json.loads(_success_payload("hello world"))
    assert result == {"ok": True, "result": "hello world"}


def test_success_payload_truncation_metadata() -> None:
    """_success_payload includes truncation fields when flagged."""
    result = json.loads(_success_payload("abc", truncated=True, original_bytes=1000))
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["original_bytes"] == 1000
    assert result["result"] == "abc"
