"""lughus — micro-framework for building A2A agents with LiteLLM."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING, Any

try:
    __version__ = _pkg_version("lughus")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

if TYPE_CHECKING:
    # Keep every lazily-exported symbol resolvable for mypy and IDEs.
    from .gateway import BaseGateway as BaseGateway
    from .llm import LLM as LLM
    from .llm import GenerateLLM as GenerateLLM
    from .llm import StreamingLLM as StreamingLLM
    from .server import BoundedInMemoryTaskStore as BoundedInMemoryTaskStore
    from .server import ProductionGuardMiddleware as ProductionGuardMiddleware
    from .server import build_app as build_app
    from .server import serve as serve

from .application import AgentRuntime, GovernedAgentRunner
from .approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from .budget import BudgetAmount, BudgetExceeded, BudgetLedger, BudgetLimit
from .budgeted_llm import BudgetedLLM
from .config import BaseSettings
from .context import ContextItem, ContextManager, ContextWindow, TrustLevel
from .coordinator import RunCoordinator
from .delegation import (
    DelegationCycleError,
    DelegationRequest,
    DelegationResult,
    Delegator,
    RemoteAgentClient,
)
from .domain import EventVisibility, Run, RunEvent, RunStatus, Usage
from .errors import (
    IdempotencyCapacityError,
    LoopLimitError,
    LughusError,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from .evaluation import EvaluationResult, Scenario, evaluate_scenario
from .event_stream import EventSink, InMemoryEventSink
from .events import Artifact, CompletionEvent, ProgressEvent
from .idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    IdempotencyStore,
    InMemoryIdempotencyStore,
)
from .loop import LoopResult, StreamingMode, ToolExecutionConfig, agent_loop, agent_loop_stream
from .mcp import MCPAdapter, MCPClient, MCPServerConfig, MCPToolDescriptor
from .persistence import (
    Checkpoint,
    CheckpointStore,
    ConcurrentUpdateError,
    EventStore,
    InMemoryRunStore,
    RunStore,
    RunUnitOfWork,
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
from .replay import REPLAY_SCHEMA_VERSION, RecordedCall, ReplayBundle, ReplayCapturePolicy
from .resume import ResumeAction, ResumeDecision, decide_resume
from .runner import AgentRunner
from .runtime import ExecutionRuntime, RuntimeConfig
from .telemetry import setup_telemetry
from .tools import ConcurrencyMode, ToolDef, ToolEffect, ToolRegistry, ToolRisk


# Symbols resolved on first access instead of at import time.
#
#   name -> (module, extra that provides its dependencies or None for base deps)
#
# Two distinct reasons to be here (W1-01 / N-01):
#   * .llm pulls in litellm, which is heavy: importing lughus should not pay for
#     it when no model call is made (CLI, cold starts, unit tests);
#   * .gateway and .server need the optional `server` extra, so importing them
#     eagerly made `pip install lughus` unusable.
_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    "LLM": (".llm", None),
    "GenerateLLM": (".llm", None),
    "StreamingLLM": (".llm", None),
    "BaseGateway": (".gateway", "server"),
    "BoundedInMemoryTaskStore": (".server", "server"),
    "ProductionGuardMiddleware": (".server", "server"),
    "build_app": (".server", "server"),
    "serve": (".server", "server"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module 'lughus' has no attribute {name!r}")
    module_name, extra = target
    try:
        module = import_module(module_name, __name__)
    except ModuleNotFoundError as exc:
        if extra is None:
            raise
        raise ImportError(
            f"lughus.{name} requires the optional '{extra}' extra. "
            f"Install it with: pip install 'lughus[{extra}]'"
        ) from exc
    value = getattr(module, name)
    globals()[name] = value  # memoise: later accesses skip __getattr__ entirely
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "LLM",
    "REPLAY_SCHEMA_VERSION",
    "AgentRunner",
    "AgentRuntime",
    "ApprovalRequest",
    "ApprovalStatus",
    "Artifact",
    "AttemptStatus",
    "BaseGateway",
    "BaseSettings",
    "BoundedInMemoryTaskStore",
    "BudgetAmount",
    "BudgetExceeded",
    "BudgetLedger",
    "BudgetLimit",
    "BudgetedLLM",
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
    "DelegationCycleError",
    "DelegationRequest",
    "DelegationResult",
    "Delegator",
    "EvaluationResult",
    "EventSink",
    "EventStore",
    "EventVisibility",
    "ExecutionAttempt",
    "ExecutionRuntime",
    "GenerateLLM",
    "GovernedAgentRunner",
    "IdempotencyCapacityError",
    "IdempotencyKey",
    "IdempotencyStore",
    "InMemoryApprovalStore",
    "InMemoryEventSink",
    "InMemoryIdempotencyStore",
    "InMemoryRunStore",
    "LeastPrivilegePolicy",
    "LoopLimitError",
    "LoopResult",
    "LughusError",
    "MCPAdapter",
    "MCPClient",
    "MCPServerConfig",
    "MCPToolDescriptor",
    "PolicyDecision",
    "Principal",
    "ProductionGuardMiddleware",
    "ProgressEvent",
    "RecordedCall",
    "RemoteAgentClient",
    "ReplayBundle",
    "ReplayCapturePolicy",
    "ResumeAction",
    "ResumeDecision",
    "Run",
    "RunCoordinator",
    "RunEvent",
    "RunStatus",
    "RunStore",
    "RunUnitOfWork",
    "RuntimeConfig",
    "SafeToolError",
    "Scenario",
    "StreamingLLM",
    "StreamingMode",
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
    "evaluate_scenario",
    "serve",
    "setup_telemetry",
]
