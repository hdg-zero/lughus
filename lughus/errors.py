"""Public exception types raised or reported by lughus."""

from __future__ import annotations

__all__ = [
    "ApprovalRequired",
    "ApprovalRequiredGroup",
    "LLMResponseError",
    "LoopLimitError",
    "LughusError",
    "RunSuspended",
    "SafeToolError",
    "ToolExecutionError",
    "ToolTimeoutError",
    "ToolValidationError",
]


class LughusError(Exception):
    """Base class for framework-level errors."""


class ToolValidationError(LughusError):
    """A tool schema, argument payload, or output failed validation."""

    retryable: bool = True


class ToolExecutionError(LughusError):
    """A tool raised an exception during execution."""

    retryable: bool = False


class ToolTimeoutError(ToolExecutionError):
    """A tool exceeded its configured timeout."""

    retryable: bool = True


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


class ApprovalRequired(LughusError):
    """A tool requires human approval before dispatch.

    NOT a ToolExecutionError: approval barriers are invisible to the model.
    """

    def __init__(self, request_id: str, tool_name: str, expires_at: str | None = None) -> None:
        super().__init__(f"Tool '{tool_name}' requires approval (request_id={request_id})")
        self.request_id = request_id
        self.tool_name = tool_name
        self.expires_at = expires_at


class ApprovalRequiredGroup(LughusError):
    """Aggregates multiple ApprovalRequired exceptions from a single turn."""

    def __init__(self, requests: list[ApprovalRequired]) -> None:
        names = ", ".join(r.tool_name for r in requests)
        super().__init__(f"Approval required for: {names}")
        self.requests = tuple(requests)


class RunSuspended(LughusError):
    """A run has been suspended waiting for approvals."""

    def __init__(self, run_id: str, pending_requests: tuple[ApprovalRequired, ...]) -> None:
        super().__init__(f"Run {run_id} suspended: {len(pending_requests)} approval(s) pending")
        self.run_id = run_id
        self.pending_requests = pending_requests


class IdempotencyCapacityError(LughusError):
    """The receipt store is saturated with non-expired in-flight attempts.

    W1-04 / N-02. Distinct from a bare RuntimeError so callers can catch it, and
    distinct from "the store is full of old receipts", which is now handled by
    eviction instead of by refusing work.
    """
