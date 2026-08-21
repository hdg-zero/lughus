"""lughus — micro-framework for building A2A agents with LiteLLM."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Keep every lazily-exported symbol resolvable for mypy and IDEs.
    from .agent.application import AgentRuntime as AgentRuntime
    from .agent.runner import AgentRunner as AgentRunner
    from .agent.runner import GovernedAgentRunner as GovernedAgentRunner
    from .core.artifacts import ArtifactStore as ArtifactStore
    from .core.event_stream import EventSink as EventSink
    from .core.event_stream import InMemoryEventSink as InMemoryEventSink
    from .engine.llm import LLM as LLM
    from .engine.llm import GenerateLLM as GenerateLLM
    from .engine.llm import StreamingLLM as StreamingLLM
    from .engine.tools import ConcurrencyMode as ConcurrencyMode
    from .engine.tools import ToolDef as ToolDef
    from .engine.tools import ToolEffect as ToolEffect
    from .engine.tools import ToolRegistry as ToolRegistry
    from .engine.tools import ToolRisk as ToolRisk
    from .governance.budget import BudgetAmount as BudgetAmount
    from .governance.budget import BudgetExceeded as BudgetExceeded
    from .governance.budget import BudgetLedger as BudgetLedger
    from .governance.budget import BudgetLimit as BudgetLimit
    from .governance.budgeted_llm import BudgetedLLM as BudgetedLLM
    from .governance.idempotency import AttemptStatus as AttemptStatus
    from .governance.idempotency import ExecutionAttempt as ExecutionAttempt
    from .governance.idempotency import IdempotencyKey as IdempotencyKey
    from .governance.idempotency import IdempotencyStore as IdempotencyStore
    from .governance.idempotency import InMemoryIdempotencyStore as InMemoryIdempotencyStore
    from .infra.runtime import ExecutionRuntime as ExecutionRuntime
    from .infra.runtime import RuntimeConfig as RuntimeConfig
    from .infra.telemetry import setup_telemetry as setup_telemetry
    from .interfaces.gateway import BaseGateway as BaseGateway
    from .interfaces.mcp import MCPAdapter as MCPAdapter
    from .interfaces.mcp import MCPClient as MCPClient
    from .interfaces.mcp import MCPServerConfig as MCPServerConfig
    from .interfaces.mcp import MCPToolDescriptor as MCPToolDescriptor
    from .interfaces.server import BoundedInMemoryTaskStore as BoundedInMemoryTaskStore
    from .interfaces.server import ProductionGuardMiddleware as ProductionGuardMiddleware
    from .interfaces.server import build_app as build_app
    from .interfaces.server import serve as serve
    from .loop import LoopResult as LoopResult
    from .loop import StreamChunk as StreamChunk
    from .loop import ToolExecutionConfig as ToolExecutionConfig
    from .loop import agent_loop as agent_loop
    from .loop import agent_loop_stream as agent_loop_stream
    from .persistence.coordinator import RunCoordinator as RunCoordinator
    from .persistence.resume import ResumeAction as ResumeAction
    from .persistence.resume import ResumeDecision as ResumeDecision
    from .persistence.resume import decide_resume as decide_resume
    from .persistence.store import Checkpoint as Checkpoint
    from .persistence.store import CheckpointStore as CheckpointStore
    from .persistence.store import ConcurrentUpdateError as ConcurrentUpdateError
    from .persistence.store import EventStore as EventStore
    from .persistence.store import InMemoryRunStore as InMemoryRunStore
    from .persistence.store import RunStore as RunStore
    from .persistence.store import RunUnitOfWork as RunUnitOfWork

# ── Eager imports: stdlib-only modules (no asyncio / third-party) ────
from .core.context import ContextItem, ContextManager, ContextWindow, TrustLevel
from .core.domain import EventVisibility, Run, RunEvent, RunStatus, Usage
from .core.errors import (
    ApprovalRequired,
    ApprovalRequiredGroup,
    ContextBudgetExceeded,
    LoopLimitError,
    LughusError,
    RunSuspended,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from .core.events import Artifact, CompletionEvent, ProgressEvent
from .governance.approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore
from .governance.policy import (
    CompositePolicy,
    DecisionKind,
    LeastPrivilegePolicy,
    PolicyDecision,
    Principal,
    ToolPolicy,
    ToolProposal,
)
from .infra.config import BaseSettings
from .persistence.replay import ReplayBundle
from .testing.evaluation import EvaluationResult, Scenario, evaluate_scenario

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
    "ArtifactStore": (".core.artifacts", None),
    # ── litellm (heavy) ─────────────────────────────────────────────
    "LLM": (".engine.llm", None),
    "GenerateLLM": (".engine.llm", None),
    "StreamingLLM": (".engine.llm", None),
    # ── server extra ─────────────────────────────────────────────────
    "BaseGateway": (".interfaces.gateway", "server"),
    "BoundedInMemoryTaskStore": (".interfaces.server", "server"),
    "ProductionGuardMiddleware": (".interfaces.server", "server"),
    "build_app": (".interfaces.server", "server"),
    "serve": (".interfaces.server", "server"),
    # ── jsonschema chain ─────────────────────────────────────────────
    "ConcurrencyMode": (".engine.tools", None),
    "ToolDef": (".engine.tools", None),
    "ToolEffect": (".engine.tools", None),
    "ToolRegistry": (".engine.tools", None),
    "ToolRisk": (".engine.tools", None),
    "MCPAdapter": (".interfaces.mcp", None),
    "MCPClient": (".interfaces.mcp", None),
    "MCPServerConfig": (".interfaces.mcp", None),
    "MCPToolDescriptor": (".interfaces.mcp", None),
    # ── opentelemetry chain ──────────────────────────────────────────
    "setup_telemetry": (".infra.telemetry", None),
    "AttemptStatus": (".governance.idempotency", None),
    "ExecutionAttempt": (".governance.idempotency", None),
    "IdempotencyKey": (".governance.idempotency", None),
    "IdempotencyStore": (".governance.idempotency", None),
    "InMemoryIdempotencyStore": (".governance.idempotency", None),
    "ResumeAction": (".persistence.resume", None),
    "ResumeDecision": (".persistence.resume", None),
    "decide_resume": (".persistence.resume", None),
    # ── jsonschema + opentelemetry ───────────────────────────────────
    "LoopResult": (".loop", None),
    "StreamChunk": (".loop", None),
    "ToolExecutionConfig": (".loop", None),
    "agent_loop": (".loop", None),
    "agent_loop_stream": (".loop", None),
    "AgentRunner": (".agent.runner", None),
    "AgentRuntime": (".agent.application", None),
    "GovernedAgentRunner": (".agent.runner", None),
    # ── asyncio chain ────────────────────────────────────────────────
    "BudgetAmount": (".governance.budget", None),
    "BudgetExceeded": (".governance.budget", None),
    "BudgetLedger": (".governance.budget", None),
    "BudgetLimit": (".governance.budget", None),
    "BudgetedLLM": (".governance.budgeted_llm", None),
    "RunCoordinator": (".persistence.coordinator", None),
    "EventSink": (".core.event_stream", None),
    "InMemoryEventSink": (".core.event_stream", None),
    "Checkpoint": (".persistence.store", None),
    "CheckpointStore": (".persistence.store", None),
    "ConcurrentUpdateError": (".persistence.store", None),
    "EventStore": (".persistence.store", None),
    "InMemoryRunStore": (".persistence.store", None),
    "RunStore": (".persistence.store", None),
    "RunUnitOfWork": (".persistence.store", None),
    "ExecutionRuntime": (".infra.runtime", None),
    "RuntimeConfig": (".infra.runtime", None),
}


def __getattr__(name: str) -> Any:
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        try:
            v = _pkg_version("lughus")
        except PackageNotFoundError:
            v = "0.0.0-dev"
        globals()["__version__"] = v
        return v
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
    "EvaluationResult",
    "EventSink",
    "EventStore",
    "EventVisibility",
    "ExecutionAttempt",
    "ExecutionRuntime",
    "GenerateLLM",
    "GovernedAgentRunner",
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
    "ReplayBundle",
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
