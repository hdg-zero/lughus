"""Infrastructure layer: config, telemetry, runtime, threading, retry."""

from importlib import import_module
from typing import Any

from ._threading import run_sync_in_thread
from .config import BaseSettings
from .retry import retry_budget
from .runtime import ExecutionRuntime, RuntimeConfig


def __getattr__(name: str) -> Any:
    if name not in {"meter", "setup_telemetry", "tracer"}:
        raise AttributeError(name)
    value = getattr(import_module(".telemetry", __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "BaseSettings",
    "ExecutionRuntime",
    "RuntimeConfig",
    "meter",
    "retry_budget",
    "run_sync_in_thread",
    "setup_telemetry",
    "tracer",
]
