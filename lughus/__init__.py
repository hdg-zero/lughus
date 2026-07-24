"""lughus — micro-framework for building A2A agents with LiteLLM."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING, Any

try:
    __version__ = _pkg_version("lughus")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

if TYPE_CHECKING:
    from .llm import LLM as LLM
    from .llm import GenerateLLM as GenerateLLM
    from .llm import StreamingLLM as StreamingLLM

from .config import BaseSettings
from .errors import (
    LoopLimitError,
    LughusError,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from .events import Artifact, CompletionEvent, ProgressEvent
from .domain import EventVisibility, Run, RunEvent, RunStatus, Usage
from .event_stream import EventSink, InMemoryEventSink
from .runner import AgentRunner
from .runtime import ExecutionRuntime, RuntimeConfig
from .gateway import BaseGateway
from .loop import LoopResult, ToolExecutionConfig, agent_loop, agent_loop_stream
from .server import BoundedInMemoryTaskStore, ProductionGuardMiddleware, build_app, serve
from .telemetry import setup_telemetry
from .tools import ToolDef, ToolRegistry


def __getattr__(name: str) -> Any:
    if name == "LLM":
        from .llm import LLM

        return LLM
    if name == "GenerateLLM":
        from .llm import GenerateLLM

        return GenerateLLM
    if name == "StreamingLLM":
        from .llm import StreamingLLM

        return StreamingLLM
    raise AttributeError(f"module 'lughus' has no attribute {name!r}")


__all__ = [
    "LLM",
    "AgentRunner",
    "Artifact",
    "BaseGateway",
    "BaseSettings",
    "BoundedInMemoryTaskStore",
    "CompletionEvent",
    "EventSink",
    "EventVisibility",
    "ExecutionRuntime",
    "GenerateLLM",
    "InMemoryEventSink",
    "LoopLimitError",
    "LoopResult",
    "LughusError",
    "ProductionGuardMiddleware",
    "ProgressEvent",
    "Run",
    "RunEvent",
    "RunStatus",
    "RuntimeConfig",
    "SafeToolError",
    "StreamingLLM",
    "ToolDef",
    "ToolExecutionConfig",
    "ToolExecutionError",
    "ToolRegistry",
    "ToolTimeoutError",
    "ToolValidationError",
    "Usage",
    "agent_loop",
    "agent_loop_stream",
    "build_app",
    "serve",
    "setup_telemetry",
]
