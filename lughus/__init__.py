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
    from .application import AgentRuntime as AgentRuntime
    from .runner import GovernedAgentRunner as GovernedAgentRunner
    from .artifacts import ArtifactStore as ArtifactStore
    from .budget import BudgetAmount as BudgetAmount
    from .budget import BudgetExceeded as BudgetExceeded
    from .budget import BudgetLedger as BudgetLedger
    from .budget import BudgetLimit as BudgetLimit
    from .budgeted_llm import BudgetedLLM as BudgetedLLM
    from .coordinator import RunCoordinator as RunCoordinator
    from .delegation import DelegationCycleError as DelegationCycleError
    from .delegation import DelegationRequest as DelegationRequest
    from .delegation import DelegationResult as DelegationResult
    from .delegation import Delegator as Delegator
    from .delegation import RemoteAgentClient as RemoteAgentClient
    from .event_stream import EventSink as EventSink
    from .event_stream import InMemoryEventSink as InMemoryEventSink
    from .gateway import BaseGateway as BaseGateway
    from .idempotency import AttemptStatus as AttemptStatus
    from .idempotency import ExecutionAttempt as ExecutionAttempt
    from .idempotency import IdempotencyKey as IdempotencyKey
    from .idempotency import IdempotencyStore as IdempotencyStore
    from .idempotency import InMemoryIdempotencyStore as InMemoryIdempotencyStore
    from .llm import LLM as LLM
    from .llm import GenerateLLM as GenerateLLM
    from .llm import StreamingLLM as StreamingLLM
    from .loop import LoopResult as LoopResult
    from .loop import StreamChunk as StreamChunk
    from .loop import StreamingMode as StreamingMode
    from .loop import ToolExecutionConfig as ToolExecutionConfig
    from .loop import agent_loop as agent_loop
    from .loop import agent_loop_stream as agent_loop_stream
    from .mcp import MCPAdapter as MCPAdapter
    from .mcp import MCPClient as MCPClient
    from .mcp import MCPServerConfig as MCPServerConfig
    from .mcp import MCPToolDescriptor as MCPToolDescriptor
    from .persistence import Checkpoint as Checkpoint
    from .persistence import CheckpointStore as CheckpointStore
    from .persistence import ConcurrentUpdateError as ConcurrentUpdateError
    from .persistence import EventStore as EventStore
    from .persistence import InMemoryRunStore as InMemoryRunStore
    from .persistence import RunStore as RunStore
    from .persistence import RunUnitOfWork as RunUnitOfWork
    from .resume import ResumeAction as ResumeAction
    from .resume import ResumeDecision as ResumeDecision
    from .resume import decide_resume as decide_resume
    from .runner import AgentRunner as AgentRunner
    from .runtime import ExecutionRuntime as ExecutionRuntime
    from .runtime import RuntimeConfig as RuntimeConfig
    from .server import BoundedInMemoryTaskStore as BoundedInMemoryTaskStore
    from .server import ProductionGuardMiddleware as ProductionGuardMiddleware
    from .server import build_app as build_app
    from .server import serve as serve
    from .telemetry import setup_telemetry as setup_telemetry
    from .tools import ConcurrencyMode as ConcurrencyMode
    from .tools import ToolDef as ToolDef
    from .tools import ToolEffect as ToolEffect
    from .tools import ToolRegistry as ToolRegistry
    from .tools import ToolRisk as ToolRisk

# ── Eager imports: stdlib-only modules (no asyncio / third-party) ────
from .approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from .config import BaseSettings
from .context import ContextItem, ContextManager, ContextWindow, TrustLevel
from .domain import EventVisibility, Run, RunEvent, RunStatus, Usage
from .errors import (
    ApprovalRequired,
    ApprovalRequiredGroup,
    ContextBudgetExceeded,
    IdempotencyCapacityError,
    LoopLimitError,
    LughusError,
    RunSuspended,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from .evaluation import EvaluationResult, Scenario, evaluate_scenario
from .events import Artifact, CompletionEvent, ProgressEvent
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

# ── Lazy-loaded symbols ─────────────────────────────────────────────
#
#   name -> (module, extra that provides its dependencies or None for base deps)
#
# Reasons to defer:
#   * .llm pulls in litellm (very heavy);
#   * .gateway / .server need the optional `server` extra;
#   * .tools and .loop pull in jsonschema;
#   * .telemetry pulls in opentelemetry;
#   * several modules pull in asyncio (~50 ms) transitively via budget,
#     persistence, event_stream, etc.
_LAZY_ATTRS: dict[str, tuple[str, str | None]] = {
    # ── artifacts (stdlib-only) ────────────────────────────────────────
    "ArtifactStore": (".artifacts", None),
    # ── litellm (heavy) ─────────────────────────────────────────────
    "LLM": (".llm", None),
    "GenerateLLM": (".llm", None),
    "StreamingLLM": (".llm", None),
    # ── server extra ─────────────────────────────────────────────────
    "BaseGateway": (".gateway", "server"),
    "BoundedInMemoryTaskStore": (".server", "server"),
    "ProductionGuardMiddleware": (".server", "server"),
    "build_app": (".server", "server"),
    "serve": (".server", "server"),
    # ── jsonschema chain ─────────────────────────────────────────────
    "ConcurrencyMode": (".tools", None),
    "ToolDef": (".tools", None),
    "ToolEffect": (".tools", None),
    "ToolRegistry": (".tools", None),
    "ToolRisk": (".tools", None),
    "MCPAdapter": (".mcp", None),
    "MCPClient": (".mcp", None),
    "MCPServerConfig": (".mcp", None),
    "MCPToolDescriptor": (".mcp", None),
    # ── opentelemetry chain ──────────────────────────────────────────
    "setup_telemetry": (".telemetry", None),
    "AttemptStatus": (".idempotency", None),
    "ExecutionAttempt": (".idempotency", None),
    "IdempotencyKey": (".idempotency", None),
    "IdempotencyStore": (".idempotency", None),
    "InMemoryIdempotencyStore": (".idempotency", None),
    "ResumeAction": (".resume", None),
    "ResumeDecision": (".resume", None),
    "decide_resume": (".resume", None),
    # ── jsonschema + opentelemetry ───────────────────────────────────
    "LoopResult": (".loop", None),
    "StreamChunk": (".loop", None),
    "StreamingMode": (".loop", None),
    "ToolExecutionConfig": (".loop", None),
    "agent_loop": (".loop", None),
    "agent_loop_stream": (".loop", None),
    "AgentRunner": (".runner", None),
    "AgentRuntime": (".application", None),
    "GovernedAgentRunner": (".runner", None),
    # ── asyncio chain ────────────────────────────────────────────────
    "BudgetAmount": (".budget", None),
    "BudgetExceeded": (".budget", None),
    "BudgetLedger": (".budget", None),
    "BudgetLimit": (".budget", None),
    "BudgetedLLM": (".budgeted_llm", None),
    "RunCoordinator": (".coordinator", None),
    "DelegationCycleError": (".delegation", None),
    "DelegationRequest": (".delegation", None),
    "DelegationResult": (".delegation", None),
    "Delegator": (".delegation", None),
    "RemoteAgentClient": (".delegation", None),
    "EventSink": (".event_stream", None),
    "InMemoryEventSink": (".event_stream", None),
    "Checkpoint": (".persistence", None),
    "CheckpointStore": (".persistence", None),
    "ConcurrentUpdateError": (".persistence", None),
    "EventStore": (".persistence", None),
    "InMemoryRunStore": (".persistence", None),
    "RunStore": (".persistence", None),
    "RunUnitOfWork": (".persistence", None),
    "ExecutionRuntime": (".runtime", None),
    "RuntimeConfig": (".runtime", None),
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
    "ApprovalRequired",
    "ApprovalRequiredGroup",
    "ApprovalStatus",
    "Artifact",
    "ArtifactStore",
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
    "ContextBudgetExceeded",
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
    "RunSuspended",
    "RunUnitOfWork",
    "RuntimeConfig",
    "SafeToolError",
    "Scenario",
    "StreamChunk",
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
