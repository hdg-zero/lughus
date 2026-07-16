"""Shared retry-budget context for LLM calls."""
from __future__ import annotations

import contextlib
import contextvars
from collections.abc import Iterator

_retry_budget_var: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "lughus_retry_budget",
    default=None,
)
_retry_used_var: contextvars.ContextVar[float] = contextvars.ContextVar(
    "lughus_retry_used",
    default=0.0,
)


@contextlib.contextmanager
def retry_budget(max_elapsed: float | None) -> Iterator[None]:
    """Share one retry sleep budget across nested LLM calls in this context."""
    budget_token = _retry_budget_var.set(max_elapsed if max_elapsed and max_elapsed > 0 else None)
    used_token = _retry_used_var.set(0.0)
    try:
        yield
    finally:
        _retry_budget_var.reset(budget_token)
        _retry_used_var.reset(used_token)
