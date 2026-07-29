from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..approval import ApprovalStore
    from ..idempotency import IdempotencyStore
    from ..policy import Principal, ToolPolicy
    from ..runtime import ExecutionRuntime


class StreamingMode(StrEnum):
    BUFFERED = "buffered"
    LIVE = "live"
    LIVE_AT_MOST_ONCE = "live_at_most_once"


DEFAULT_MAX_ITERATIONS = 50
DEFAULT_MAX_PARALLEL_TOOLS = 8
DEFAULT_MAX_GLOBAL_TOOLS = 64
DEFAULT_MAX_TOOL_ARGS_CHARS = 20_000
DEFAULT_MAX_TOOL_OUTPUT_CHARS = 20_000
DEFAULT_MAX_SYNC_THREAD_WORKERS = 32
DEFAULT_MAX_MESSAGE_HISTORY_CHARS = 200_000
DEFAULT_TOOL_QUEUE_TIMEOUT = 30.0


@dataclass(frozen=True)
class ToolExecutionConfig:
    """Runtime guardrails for tool execution.

    ``tool_timeout`` is per tool call. Set it to ``None`` or ``<= 0`` to disable.
    ``max_parallel_tools`` limits concurrency within one agent loop iteration.
    ``max_global_tools`` limits tool calls across the current event loop / worker.
    """

    max_parallel_tools: int = DEFAULT_MAX_PARALLEL_TOOLS
    tool_timeout: float | None = None
    max_global_tools: int = DEFAULT_MAX_GLOBAL_TOOLS
    max_tool_args_chars: int = DEFAULT_MAX_TOOL_ARGS_CHARS
    max_tool_output_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS
    max_sync_thread_workers: int = DEFAULT_MAX_SYNC_THREAD_WORKERS
    max_message_history_chars: int = DEFAULT_MAX_MESSAGE_HISTORY_CHARS
    tool_queue_timeout: float | None = DEFAULT_TOOL_QUEUE_TIMEOUT
    compact_tool_schemas: bool = False
    runtime: ExecutionRuntime | None = field(default=None, repr=False, compare=False)
    policy: ToolPolicy | None = field(default=None, repr=False, compare=False)
    principal: Principal | None = field(default=None, repr=False, compare=False)
    approval_store: ApprovalStore | None = field(default=None, repr=False, compare=False)
    idempotency_store: IdempotencyStore | None = field(default=None, repr=False, compare=False)
    run_id: str = "untracked"

    def __post_init__(self) -> None:
        positive = {
            "max_parallel_tools": self.max_parallel_tools,
            "max_global_tools": self.max_global_tools,
            "max_tool_args_chars": self.max_tool_args_chars,
            "max_tool_output_chars": self.max_tool_output_chars,
            "max_sync_thread_workers": self.max_sync_thread_workers,
            "max_message_history_chars": self.max_message_history_chars,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise ValueError(f"Tool execution limits must be positive: {', '.join(invalid)}")
