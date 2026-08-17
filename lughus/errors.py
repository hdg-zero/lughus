"""Public exception types raised or reported by lughus."""

from __future__ import annotations

__all__ = [
    "LLMResponseError",
    "LoopLimitError",
    "LughusError",
    "SafeToolError",
    "ToolExecutionError",
    "ToolTimeoutError",
    "ToolValidationError",
]


class LughusError(Exception):
    """Base class for framework-level errors."""


class ToolValidationError(LughusError):
    """A tool schema, argument payload, or output failed validation."""


class ToolExecutionError(LughusError):
    """A tool raised an exception during execution."""


class ToolTimeoutError(ToolExecutionError):
    """A tool exceeded its configured timeout."""


class LoopLimitError(LughusError, RuntimeError):
    """The agent loop exceeded its configured iteration limit."""


class LLMResponseError(LughusError):
    """An LLM provider returned a response without a usable completion choice."""


class SafeToolError(ToolExecutionError):
    """Business error whose message may be shown to the model.

    Unknown exceptions are deliberately redacted. Tool authors must opt in to exposing a
    message by raising this type with a stable, non-sensitive ``code``.
    """

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.retryable = retryable


class IdempotencyCapacityError(LughusError):
    """The receipt store is saturated with non-expired in-flight attempts.

    W1-04 / N-02. Distinct from a bare RuntimeError so callers can catch it, and
    distinct from "the store is full of old receipts", which is now handled by
    eviction instead of by refusing work.
    """
