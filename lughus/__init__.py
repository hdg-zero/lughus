"""lughus — micro-framework for building A2A agents with LiteLLM."""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Keep every lazily-exported symbol resolvable for mypy and IDEs.
    from .agent.application import AgentRuntime as AgentRuntime
    from .agent.runner import GovernedAgentRunner as GovernedAgentRunner
    from .core.artifacts import ArtifactStore as ArtifactStore
    from .core.event_stream import EventSink as EventSink
    from .core.event_stream import InMemoryEventSink as InMemoryEventSink
    from .engine.delegation import DelegationCycleError as DelegationCycleError
    from .engine.delegation import DelegationRequest as DelegationRequest
    from .engine.delegation import DelegationResult as DelegationResult
    from .engine.delegation import Delegator as Delegator
    from .engine.delegation import RemoteAgentClient as RemoteAgentClient
    from .engine.interpreter import InterpreterResult as InterpreterResult
    from .engine.interpreter import InterpreterTimeoutError as InterpreterTimeoutError
    from .engine.interpreter import register_code_interpreter as register_code_interpreter
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
    from .loop import emit_a2a_request as emit_a2a_request
    from .loop import emit_a2a_response as emit_a2a_response
    from .persistence.coordinator import RunCoordinator as RunCoordinator
    from .persistence.store import Checkpoint as Checkpoint
    from .persistence.store import CheckpointStore as CheckpointStore
    from .persistence.store import ConcurrentUpdateError as ConcurrentUpdateError
    from .persistence.store import EventStore as EventStore
    from .persistence.store import InMemoryRunStore as InMemoryRunStore
    from .persistence.store import RunStore as RunStore
    from .persistence.store import RunUnitOfWork as RunUnitOfWork

# ── Eager imports: Core Tier-1 ──────────────────────────────────────
from .core.errors import LughusError, SafeToolError
from .core.events import CompletionEvent, ProgressEvent
from .infra.config import BaseSettings

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
    # ── artifacts & context (core) ───────────────────────────────────
    "Artifact": (".core.events", None),
    "ArtifactStore": (".core.artifacts", None),
    "ContextItem": (".core.context", None),
    "ContextManager": (".core.context", None),
    "ContextWindow": (".core.context", None),
    "TrustLevel": (".core.context", None),
    # ── domain (core) ────────────────────────────────────────────────
    "EventVisibility": (".core.domain", None),
    "Run": (".core.domain", None),
    "RunEvent": (".core.domain", None),
    "RunStatus": (".core.domain", None),
    "Usage": (".core.domain", None),
    # ── errors (core) ────────────────────────────────────────────────
    "ApprovalRequired": (".core.errors", None),
    "ApprovalRequiredGroup": (".core.errors", None),
    "ContextBudgetExceeded": (".core.errors", None),
    "IdempotencyCapacityError": (".core.errors", None),
    "LLMResponseError": (".core.errors", None),
    "LoopLimitError": (".core.errors", None),
    "RunSuspended": (".core.errors", None),
    "ToolExecutionError": (".core.errors", None),
    "ToolTimeoutError": (".core.errors", None),
    "ToolValidationError": (".core.errors", None),
    # ── approval (governance) ────────────────────────────────────────
    "ApprovalRequest": (".governance.approval", None),
    "ApprovalStatus": (".governance.approval", None),
    "InMemoryApprovalStore": (".governance.approval", None),
    # ── policy (governance) ──────────────────────────────────────────
    "CompositePolicy": (".governance.policy", None),
    "DecisionKind": (".governance.policy", None),
    "LeastPrivilegePolicy": (".governance.policy", None),
    "PolicyDecision": (".governance.policy", None),
    "Principal": (".governance.policy", None),
    "ToolPolicy": (".governance.policy", None),
    "ToolProposal": (".governance.policy", None),
    # ── evaluation (testing) ─────────────────────────────────────────
    "EvaluationResult": (".testing.evaluation", None),
    "Scenario": (".testing.evaluation", None),
    "evaluate_scenario": (".testing.evaluation", None),
    # ── delegation (engine) ──────────────────────────────────────────
    "DelegationCycleError": (".engine.delegation", None),
    "DelegationRequest": (".engine.delegation", None),
    "DelegationResult": (".engine.delegation", None),
    "Delegator": (".engine.delegation", None),
    "RemoteAgentClient": (".engine.delegation", None),
    # ── interpreter (engine) ─────────────────────────────────────────
    "InterpreterResult": (".engine.interpreter", None),
    "InterpreterTimeoutError": (".engine.interpreter", None),
    "register_code_interpreter": (".engine.interpreter", None),
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
    # ── jsonschema + opentelemetry ───────────────────────────────────
    "LoopResult": (".loop", None),
    "StreamChunk": (".loop", None),
    "ToolExecutionConfig": (".loop", None),
    "agent_loop": (".loop", None),
    "agent_loop_stream": (".loop", None),
    "emit_a2a_request": (".loop", None),
    "emit_a2a_response": (".loop", None),
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
            return _pkg_version("lughus")
        except PackageNotFoundError:
            return "0.0.0.dev0"

    if name not in _LAZY_ATTRS:
        raise AttributeError(f"module 'lughus' has no attribute {name!r}")
    mod_path, extra = _LAZY_ATTRS[name]
    try:
        module = import_module(mod_path, package=__name__)
    except ImportError as exc:
        if extra:
            raise ImportError(
                f"lughus.{name} requires the '{extra}' extra: pip install 'lughus[{extra}]'"
            ) from exc
        raise ImportError(
            f"Failed to import lughus.{name}: {exc}. "
            f"Install the missing dependency to use this feature."
        ) from exc
    value = getattr(module, name)
    globals()[name] = value  # memoise: later accesses skip __getattr__ entirely
    return value


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "LLM",
    "AgentRuntime",
    "BaseGateway",
    "BaseSettings",
    "CompletionEvent",
    "ConcurrencyMode",
    "GovernedAgentRunner",
    "LoopResult",
    "LughusError",
    "ProgressEvent",
    "SafeToolError",
    "ToolEffect",
    "ToolExecutionConfig",
    "ToolRegistry",
    "ToolRisk",
    "agent_loop",
    "agent_loop_stream",
    "build_app",
    "register_code_interpreter",
    "serve",
]
