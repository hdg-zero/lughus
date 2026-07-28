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

from .approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from .budget import BudgetAmount, BudgetExceeded, BudgetLedger, BudgetLimit
from .config import BaseSettings
from .context import ContextItem, ContextManager, ContextWindow, TrustLevel
from .domain import EventVisibility, Run, RunEvent, RunStatus, Usage
from .errors import (
    LoopLimitError,
    LughusError,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from .event_stream import EventSink, InMemoryEventSink
from .events import Artifact, CompletionEvent, ProgressEvent
from .gateway import BaseGateway
from .loop import LoopResult, ToolExecutionConfig, agent_loop, agent_loop_stream
from .persistence import (
    Checkpoint,
    CheckpointStore,
    ConcurrentUpdateError,
    EventStore,
    InMemoryDurableStore,
    RunStore,
)
from .policy import (
    CompositePolicy,
    DecisionKind,
    LeastPrivilegePolicy,
    PolicyDecision,
    Principal,
    ToolPolicy,
    ToolProposal,
)
from .resume import ResumeAction, ResumeDecision, decide_resume
from .runner import AgentRunner
from .runtime import ExecutionRuntime, RuntimeConfig
from .server import BoundedInMemoryTaskStore, ProductionGuardMiddleware, build_app, serve
from .telemetry import setup_telemetry
from .tools import ConcurrencyMode, ToolDef, ToolEffect, ToolRegistry, ToolRisk


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
    "ApprovalRequest",
    "ApprovalStatus",
    "Artifact",
    "BaseGateway",
    "BaseSettings",
    "BoundedInMemoryTaskStore",
    "BudgetAmount",
    "BudgetExceeded",
    "BudgetLedger",
    "BudgetLimit",
    "Checkpoint",
    "CheckpointStore",
    "CompletionEvent",
    "CompositePolicy",
    "ConcurrencyMode",
    "ConcurrentUpdateError",
    "ContextItem",
    "ContextManager",
    "ContextWindow",
    "DecisionKind",
    "EventSink",
    "EventStore",
    "EventVisibility",
    "ExecutionRuntime",
    "GenerateLLM",
    "InMemoryApprovalStore",
    "InMemoryDurableStore",
    "InMemoryEventSink",
    "LeastPrivilegePolicy",
    "LoopLimitError",
    "LoopResult",
    "LughusError",
    "PolicyDecision",
    "Principal",
    "ProductionGuardMiddleware",
    "ProgressEvent",
    "ResumeAction",
    "ResumeDecision",
    "Run",
    "RunEvent",
    "RunStatus",
    "RunStore",
    "RuntimeConfig",
    "SafeToolError",
    "StreamingLLM",
    "ToolDef",
    "ToolEffect",
    "ToolExecutionConfig",
    "ToolExecutionError",
    "ToolPolicy",
    "ToolProposal",
    "ToolRegistry",
    "ToolRisk",
    "ToolTimeoutError",
    "ToolValidationError",
    "TrustLevel",
    "Usage",
    "agent_loop",
    "agent_loop_stream",
    "build_app",
    "decide_resume",
    "serve",
    "setup_telemetry",
]
