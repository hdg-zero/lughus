from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .._defaults import (
    DEFAULT_ARTIFACT_PROJECTION_THRESHOLD,
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_GLOBAL_TOOLS,
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_MAX_PARALLEL_TOOLS,
    DEFAULT_MAX_SYNC_THREAD_WORKERS,
    DEFAULT_MAX_TOOL_ARGS_CHARS,
    DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    DEFAULT_TOOL_QUEUE_TIMEOUT,
)

if TYPE_CHECKING:
    from ..approval import ApprovalStore
    from ..artifacts import ArtifactStore
    from ..idempotency import IdempotencyStore
    from ..policy import Principal, ToolPolicy
    from ..runtime import ExecutionRuntime


class StreamingMode(StrEnum):
    BUFFERED = "buffered"
    LIVE = "live"


@dataclass(frozen=True)
class ToolExecutionConfig:
    """Runtime guardrails for tool execution.

    ``tool_timeout`` is per tool call. Set it to ``None`` or ``<= 0`` to disable.
    ``max_parallel_tools`` limits concurrency within one agent loop iteration.
    ``max_global_tools`` and ``max_sync_thread_workers`` are runtime capacities
    used when ``_resolve_tool_config`` creates an implicit runtime.

    This object is inert: constructing it allocates nothing. See the ``runtime``
    field for how the execution runtime is created and owned.
    """

    max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS
    max_global_tools: int = DEFAULT_MAX_GLOBAL_TOOLS
    max_sync_thread_workers: int = DEFAULT_MAX_SYNC_THREAD_WORKERS
    tool_timeout: float | None = 30.0
    max_tool_args_chars: int = DEFAULT_MAX_TOOL_ARGS_CHARS
    max_tool_output_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    tool_queue_timeout: float | None = DEFAULT_TOOL_QUEUE_TIMEOUT
    # Stays None. A configuration is a value and must never allocate
    # a system resource -- __post_init__ used to build an ExecutionRuntime here,
    # so merely constructing a config spawned 32 threads that nothing closed.
    # agent_loop()/agent_loop_stream() now create and close a runtime when this is
    # None. Inject one explicitly to share a single thread pool across runs.
    runtime: ExecutionRuntime | None = field(default=None, repr=False, compare=False)
    policy: ToolPolicy | None = field(default=None, repr=False, compare=False)
    principal: Principal | None = field(default=None, repr=False, compare=False)
    approval_store: ApprovalStore | None = field(default=None, repr=False, compare=False)
    idempotency_store: IdempotencyStore | None = field(default=None, repr=False, compare=False)
    budget: Any = field(default=None, repr=False, compare=False)
    run_id: str = "untracked"
    artifact_projection: bool = False
    artifact_projection_threshold: int = DEFAULT_ARTIFACT_PROJECTION_THRESHOLD
    artifact_store: ArtifactStore | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        positive = {
            "max_parallel_tools": self.max_parallel_tools,
            "max_tool_args_chars": self.max_tool_args_chars,
            "max_tool_output_chars": self.max_tool_output_chars,
            "max_context_tokens": self.max_context_tokens,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"Tool execution limits must be positive: {', '.join(invalid)}")
