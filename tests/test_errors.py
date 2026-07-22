"""Tests for SafeToolError and exception redaction logic (v0.1.3)."""

from __future__ import annotations

import json

from lughus.errors import SafeToolError, ToolExecutionError
from lughus.loop._execute import _error_payload


def test_safe_tool_error_attributes() -> None:
    """SafeToolError preserves code, message, and retryable flag."""
    err = SafeToolError(code="INVALID_RANGE", message="Out of bounds", retryable=True)

    assert err.code == "INVALID_RANGE"
    assert err.public_message == "Out of bounds"
    assert err.retryable is True
    assert isinstance(err, ToolExecutionError)


def test_error_payload_redacts_unknown_exceptions() -> None:
    """Unknown exceptions are redacted in _error_payload to prevent info leaks."""
    exc = ValueError("sensitive internal db string /var/secret")
    payload = json.loads(_error_payload(exc))

    assert payload["error"] == "Tool execution failed"
    assert payload["error_code"] == "ValueError"
    assert payload["retryable"] is False


def test_error_payload_preserves_safe_tool_error() -> None:
    """SafeToolError messages are preserved in _error_payload."""
    exc = SafeToolError(code="RATE_LIMIT", message="Quota exceeded", retryable=True)
    payload = json.loads(_error_payload(exc))

    assert payload["error"] == "Quota exceeded"
    assert payload["error_code"] == "RATE_LIMIT"
    assert payload["retryable"] is True
