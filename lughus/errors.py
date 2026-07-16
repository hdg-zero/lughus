"""Public exception types raised or reported by lughus."""
from __future__ import annotations


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
