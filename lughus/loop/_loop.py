from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import StatusCode

from ..core._defaults import DEFAULT_MAX_ITERATIONS
from ..core.artifacts import ArtifactStore
from ..core.errors import LoopLimitError
from ..engine.tools import ToolRegistry
from ..infra.retry import retry_budget
from ..infra.telemetry import meter, tracer
from ._config import (
    StreamingMode,
    ToolExecutionConfig,
)
from ._execute import (
    _assistant_tool_message,
    _execute_tools,
    _loop_duration,
    _record_llm_usage,
)
from ._messages import MessageHistory, _message_tokens, render_context_messages
from ._result import LoopResult, StreamChunk

_logger = logging.getLogger(__name__)

_pruned_groups_counter = meter.create_counter(
    "lughus.context.pruned_groups",
    description="Number of atomic message groups pruned for context budget",
)
_estimated_tokens_histogram = meter.create_histogram(
    "lughus.context.estimated_tokens",
    description="Estimated token count of the message history after pruning",
)

if TYPE_CHECKING:
    from ..core.context import ContextItem
    from ..engine.llm import GenerateLLM, StreamingLLM
    from ..infra.runtime import ExecutionRuntime


_FETCH_ARTIFACT_TOOL = "fetch_artifact"
_FETCH_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact_id": {"type": "string"},
        "offset": {"type": "integer", "default": 0},
        "length": {"type": "integer"},
    },
    "required": ["artifact_id"],
}

_active_artifact_store: contextvars.ContextVar[ArtifactStore | None] = contextvars.ContextVar(
    "_active_artifact_store", default=None
)


async def _fetch_artifact_impl(
    *,
    state: Any,
    artifact_id: str,
    offset: int = 0,
    length: int | None = None,
) -> str:
    """Built-in tool: retrieve a stored artifact by id."""
    store = _active_artifact_store.get()
    if store is None:
        raise RuntimeError("No artifact store is active")
    return store.fetch_artifact(artifact_id, offset, length)


def _setup_artifact_projection(
    registry: ToolRegistry,
    tool_names: list[str],
    cfg: ToolExecutionConfig,
) -> ToolExecutionConfig:
    """Wire up artifact projection when enabled.

    Creates an :class:`ArtifactStore`, registers the ``fetch_artifact``
    built-in tool on *registry* (idempotent), appends the tool name to
    *tool_names*, and returns a new config carrying the store.

    The store is exposed to the tool function via a :mod:`contextvars`
    variable so that a registry shared across runs always resolves the
    current run's store.
    """
    if not cfg.artifact_projection:
        return cfg
    store = ArtifactStore()

    if _FETCH_ARTIFACT_TOOL not in registry:
        registry.tool(
            _FETCH_ARTIFACT_TOOL,
            "Retrieve the full or partial content of a previously stored artifact.",
            _FETCH_ARTIFACT_SCHEMA,
        )(_fetch_artifact_impl)

    if _FETCH_ARTIFACT_TOOL not in tool_names:
        tool_names.append(_FETCH_ARTIFACT_TOOL)

    return replace(cfg, artifact_store=store)


def _prepare_loop(
    system: str,
    context: str,
    registry: ToolRegistry,
    tool_names: list[str],
    cfg: ToolExecutionConfig,
    context_items: Sequence[ContextItem] = (),
) -> tuple[MessageHistory, tuple[dict, ...], int]:
    history = MessageHistory()
    history.append({"role": "system", "content": system})
    # Context items go BEFORE the user objective so they are part of
    # the cacheable prefix (rule A1: byte-identical across turns).
    history.extend(render_context_messages(context_items))
    history.append({"role": "user", "content": context})
    # prefix_len = system + context items + user objective — never pruned.
    prefix_len = len(history)
    # declarations are memoized and frozen — no deepcopy needed.
    tools = registry.declarations(
        tool_names,
        strict=True,
    )
    return history, tools, prefix_len


def _prune_if_needed(
    history: MessageHistory,
    cfg: ToolExecutionConfig,
    prefix_len: int,
    model: str,
) -> None:
    """Prune oldest atomic groups if estimated tokens exceed the budget.

    Emits ``lughus.context.pruned_groups`` and ``lughus.context.estimated_tokens``
    telemetry when pruning occurs.
    """
    max_tokens = cfg.max_context_tokens
    pruned = history.prune(max_tokens, prefix_len, model=model)
    if pruned > 0:
        attrs = {"gen_ai.request.model": model}
        _pruned_groups_counter.add(pruned, attrs)
        estimated = sum(_message_tokens(m, model=model) for m in history.view)
        _estimated_tokens_histogram.record(estimated, attrs)
        _logger.info(
            "Context budget: pruned %d group(s), ~%d tokens remaining",
            pruned,
            estimated,
        )


async def _run_tool_calls(
    tool_calls: list[tuple[str, str, str]],
    history: MessageHistory,
    registry: ToolRegistry,
    state: Any,
    cfg: ToolExecutionConfig,
    assistant_tool_calls_payload: list[dict],
    content: str | None = None,
) -> None:
    history.append(
        _assistant_tool_message(
            assistant_tool_calls_payload,
            content=content,
        )
    )
    results = await _execute_tools(tool_calls, registry, state, cfg)
    for tc_id, output in results:
        history.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": output,
            }
        )


def _finalize_loop(
    span: Any,
    text: str,
    iteration: int,
    t0: float,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    model: str,
) -> LoopResult:
    elapsed = time.perf_counter() - t0
    result = LoopResult(
        text,
        iterations=iteration + 1,
        elapsed=elapsed,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
    )
    span.set_attribute("lughus.iterations", result.iterations)
    span.set_attribute("lughus.elapsed_s", round(elapsed, 2))
    span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
    span.set_attribute("gen_ai.usage.cached_tokens", cached_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", result.total_tokens)
    span.set_status(StatusCode.OK)
    _loop_duration.record(elapsed, {"gen_ai.request.model": model})
    return result


async def _stream_with_timeout(
    stream: AsyncIterator[Any], timeout: float | None
) -> AsyncIterator[Any]:
    """Yield stream chunks, bounding the wait for each next chunk."""
    normalized_timeout = timeout if timeout and timeout > 0 else None
    iterator = stream.__aiter__()
    while True:
        try:
            if normalized_timeout:
                chunk = await asyncio.wait_for(iterator.__anext__(), normalized_timeout)
            else:
                chunk = await iterator.__anext__()
        except StopAsyncIteration:
            return
        yield chunk


def _resolve_tool_config(
    tool_config: ToolExecutionConfig | None,
) -> tuple[ToolExecutionConfig, ExecutionRuntime | None]:
    """Return a runnable config plus the runtime this loop must close.

    A ``ToolExecutionConfig`` is a value: it no longer
    allocates an ``ExecutionRuntime`` (and therefore a thread pool) in
    ``__post_init__``.  The loop owns the runtime it creates and closes it in a
    ``finally``; a runtime injected by the caller stays the caller's property and
    is never closed here.

    ``max_global_tools`` and ``max_sync_thread_workers`` are capacities of the
    runtime, not per-loop guardrails.  The implicit runtime is built from the
    module-level constants; ``tool_queue_timeout`` is still read from the config.
    """
    from ..infra.runtime import ExecutionRuntime, RuntimeConfig

    cfg = tool_config if tool_config is not None else ToolExecutionConfig()
    if cfg.runtime is not None:
        return cfg, None

    runtime = ExecutionRuntime(
        RuntimeConfig(
            max_global_tools=cfg.max_global_tools,
            max_sync_workers=cfg.max_sync_thread_workers,
            queue_timeout=cfg.tool_queue_timeout,
        )
    )
    return replace(cfg, runtime=runtime), runtime


async def agent_loop(
    llm: GenerateLLM,
    *,
    system: str,
    context: str,
    registry: ToolRegistry,
    tool_names: list[str],
    state: Any = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tool_config: ToolExecutionConfig | None = None,
    context_items: Sequence[ContextItem] = (),
) -> LoopResult:
    """Run an agentic loop until the LLM produces a text response.

    Returns a :class:`LoopResult` — a ``str`` subclass with attached usage
    metadata (``iterations``, ``elapsed``, ``prompt_tokens``,
    ``completion_tokens``, ``cached_tokens``, ``total_tokens``).
    """
    cfg, _owned_runtime = _resolve_tool_config(tool_config)
    effective_tool_names = list(tool_names)
    cfg = _setup_artifact_projection(registry, effective_tool_names, cfg)
    _artifact_token = _active_artifact_store.set(cfg.artifact_store)
    try:
        with tracer.start_as_current_span("agent_loop") as loop_span:  # noqa: SIM117
            with retry_budget(getattr(llm, "retry_max_elapsed", None)):
                loop_span.set_attribute("gen_ai.system", "litellm")
                loop_span.set_attribute("gen_ai.request.model", llm.model)
                loop_span.set_attribute("gen_ai.operation.name", "chat")
                loop_span.set_attribute("lughus.max_iterations", max_iterations)

                history, tools, prefix_len = _prepare_loop(
                    system,
                    context,
                    registry,
                    effective_tool_names,
                    cfg,
                    context_items,
                )

                t0 = time.perf_counter()
                prompt_tokens = 0
                completion_tokens = 0
                cached_tokens = 0

                for iteration in range(max_iterations):
                    _prune_if_needed(history, cfg, prefix_len, llm.model)
                    with tracer.start_as_current_span("llm.generate") as llm_span:
                        llm_span.set_attribute("gen_ai.request.model", llm.model)
                        llm_span.set_attribute("lughus.iteration", iteration + 1)
                        response = await llm.generate(
                            messages=history.view,
                            tools=tools,
                        )

                        if hasattr(response, "usage") and response.usage:
                            p, c, ca = _record_llm_usage(
                                llm_span,
                                response.usage,
                                llm.model,
                            )
                            prompt_tokens += p
                            completion_tokens += c
                            cached_tokens += ca

                    msg = response.choices[0].message

                    if not msg.tool_calls:
                        if not (msg.content or ""):
                            _logger.warning(
                                "LLM returned neither content nor tool calls at iteration %d",
                                iteration + 1,
                            )
                        return _finalize_loop(
                            loop_span,
                            msg.content or "",
                            iteration,
                            t0,
                            prompt_tokens,
                            completion_tokens,
                            cached_tokens,
                            llm.model,
                        )

                    assistant_tool_payload = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                    tc_inputs = [
                        (tc.id or "", tc.function.name or "", tc.function.arguments or "")
                        for tc in msg.tool_calls
                    ]

                    await _run_tool_calls(
                        tc_inputs,
                        history,
                        registry,
                        state,
                        cfg,
                        assistant_tool_payload,
                        content=msg.content,
                    )

                loop_span.set_status(StatusCode.ERROR, "max iterations exceeded")
                raise LoopLimitError(f"Agent loop exceeded {max_iterations} iterations")
    finally:
        _active_artifact_store.reset(_artifact_token)
        if _owned_runtime is not None:
            await _owned_runtime.close()


async def agent_loop_stream(
    llm: StreamingLLM,
    *,
    system: str,
    context: str,
    registry: ToolRegistry,
    tool_names: list[str],
    state: Any = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tool_config: ToolExecutionConfig | None = None,
    streaming_mode: str | StreamingMode = StreamingMode.BUFFERED,
    context_items: Sequence[ContextItem] = (),
) -> AsyncGenerator[StreamChunk | LoopResult, None]:
    """Streaming variant of :func:`agent_loop`.

    Yields :class:`StreamChunk` objects for provisional content and a single
    :class:`LoopResult` as the final value.  Consumers can distinguish the two
    with ``isinstance`` or by checking ``chunk.final``.
    """
    mode_str = str(streaming_mode)
    if mode_str not in {"buffered", "live"}:
        raise ValueError("streaming_mode must be 'buffered' or 'live'")
    streaming_mode_normalized = mode_str
    cfg, _owned_runtime = _resolve_tool_config(tool_config)
    effective_tool_names = list(tool_names)
    cfg = _setup_artifact_projection(registry, effective_tool_names, cfg)
    _artifact_token = _active_artifact_store.set(cfg.artifact_store)
    try:
        with tracer.start_as_current_span("agent_loop") as loop_span:  # noqa: SIM117
            with retry_budget(getattr(llm, "retry_max_elapsed", None)):
                loop_span.set_attribute("gen_ai.system", "litellm")
                loop_span.set_attribute("gen_ai.request.model", llm.model)
                loop_span.set_attribute("gen_ai.operation.name", "chat")
                loop_span.set_attribute("lughus.max_iterations", max_iterations)
                loop_span.set_attribute("lughus.streaming", True)

                history, tools, prefix_len = _prepare_loop(
                    system,
                    context,
                    registry,
                    effective_tool_names,
                    cfg,
                    context_items,
                )

                t0 = time.perf_counter()
                prompt_tokens = 0
                completion_tokens = 0
                cached_tokens = 0

                for iteration in range(max_iterations):
                    _prune_if_needed(history, cfg, prefix_len, llm.model)
                    content_parts: list[str] = []
                    tc_map: dict[int, dict[str, str]] = {}

                    with tracer.start_as_current_span("llm.generate") as llm_span:
                        llm_span.set_attribute("gen_ai.request.model", llm.model)
                        llm_span.set_attribute("lughus.iteration", iteration + 1)

                        stream = await llm.astream(messages=history.view, tools=tools)
                        timeout = getattr(llm, "timeout", None)
                        async for chunk in _stream_with_timeout(stream, timeout):
                            _usage_recorded = False

                            if not chunk.choices:
                                if hasattr(chunk, "usage") and chunk.usage:
                                    p, c, ca = _record_llm_usage(
                                        llm_span,
                                        chunk.usage,
                                        llm.model,
                                    )
                                    prompt_tokens += p
                                    completion_tokens += c
                                    cached_tokens += ca
                                    _usage_recorded = True
                                continue

                            delta = chunk.choices[0].delta
                            if not delta:
                                continue

                            if delta.content:
                                content_parts.append(delta.content)
                                if streaming_mode_normalized == "live":
                                    yield StreamChunk(content=delta.content)

                            if delta.tool_calls:
                                for tc_delta in delta.tool_calls:
                                    idx = tc_delta.index
                                    if idx not in tc_map:
                                        tc_map[idx] = {
                                            "id": "",
                                            "name": "",
                                            "arguments": "",
                                        }
                                    if tc_delta.id:
                                        tc_map[idx]["id"] = tc_delta.id
                                    if tc_delta.function:
                                        if tc_delta.function.name:
                                            tc_map[idx]["name"] += tc_delta.function.name
                                        if tc_delta.function.arguments:
                                            tc_map[idx]["arguments"] += tc_delta.function.arguments

                            if not _usage_recorded and hasattr(chunk, "usage") and chunk.usage:
                                p, c, ca = _record_llm_usage(
                                    llm_span,
                                    chunk.usage,
                                    llm.model,
                                )
                                prompt_tokens += p
                                completion_tokens += c
                                cached_tokens += ca

                    full_content = "".join(content_parts)

                    if not tc_map:
                        if streaming_mode_normalized == "buffered":
                            for content in content_parts:
                                yield StreamChunk(content=content)
                        yield _finalize_loop(
                            loop_span,
                            full_content,
                            iteration,
                            t0,
                            prompt_tokens,
                            completion_tokens,
                            cached_tokens,
                            llm.model,
                        )
                        return

                    sorted_tcs = [tc_map[i] for i in sorted(tc_map)]
                    assistant_tool_payload = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in sorted_tcs
                    ]
                    tc_inputs = [(tc["id"], tc["name"], tc["arguments"]) for tc in sorted_tcs]

                    await _run_tool_calls(
                        tc_inputs,
                        history,
                        registry,
                        state,
                        cfg,
                        assistant_tool_payload,
                        content=full_content,
                    )

                loop_span.set_status(StatusCode.ERROR, "max iterations exceeded")
                raise LoopLimitError(f"Agent loop exceeded {max_iterations} iterations")
    finally:
        _active_artifact_store.reset(_artifact_token)
        if _owned_runtime is not None:
            await _owned_runtime.close()
