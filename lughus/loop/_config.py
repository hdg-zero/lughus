from dataclasses import dataclass

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
