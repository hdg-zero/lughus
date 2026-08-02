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

from .application import AgentRuntime
from .approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from .budget import BudgetAmount, BudgetExceeded, BudgetLedger, BudgetLimit
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
from .gateway import BaseGateway
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
    InMemoryDurableStore,
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
from .replay import REPLAY_SCHEMA_VERSION, RecordedCall, ReplayBundle
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
    "IdempotencyKey",
    "IdempotencyStore",
    "InMemoryApprovalStore",
    "InMemoryDurableStore",
    "InMemoryEventSink",
    "InMemoryIdempotencyStore",
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
