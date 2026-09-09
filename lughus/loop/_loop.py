from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping, Sequence
from contextlib import aclosing, asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import StatusCode

from ..core._defaults import DEFAULT_MAX_ITERATIONS
from ..core.artifacts import ArtifactStore
from ..core.errors import LoopLimitError
from ..engine.tools import ToolDef, ToolRegistry
from ..infra.retry import retry_budget
from ..infra.telemetry import meter, tracer
from ..persistence.execution import LoopCheckpoint
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
    store = cfg.artifact_store if cfg.artifact_store is not None else ArtifactStore()

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
    if cfg.loop_state is not None and cfg.loop_state.messages:
        history = MessageHistory()
        history.extend(cfg.loop_state.messages)
        prefix_len = cfg.loop_state.prefix_len
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


def _format_tool_calls(
    tool_calls: Sequence[Any],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    """Format tool calls into provider payload and execution input tuples."""
    payload, inputs = [], []
    for tc in tool_calls:
        if isinstance(tc, Mapping):
            tc_id = str(tc.get("id") or "")
            name, args = str(tc.get("name") or ""), str(tc.get("arguments") or "")
        else:
            fn = getattr(tc, "function", None)
            tc_id = str(getattr(tc, "id", "") or "")
            name = str(getattr(fn, "name", "") or "") if fn else ""
            args = str(getattr(fn, "arguments", "") or "") if fn else ""
        payload.append(
            {"id": tc_id, "type": "function", "function": {"name": name, "arguments": args}}
        )
        inputs.append((tc_id, name, args))
    return payload, inputs


async def _save_loop(
    checkpoint: LoopCheckpoint, history: MessageHistory, cfg: ToolExecutionConfig
) -> None:
    checkpoint.messages = list(history.view)
    if cfg.on_checkpoint is not None:
        await cfg.on_checkpoint(checkpoint)


async def _finish_pending(
    checkpoint: LoopCheckpoint,
    history: MessageHistory,
    registry: ToolRegistry,
    state: Any,
    cfg: ToolExecutionConfig,
) -> None:
    dispatch = replace(cfg, turn_id=checkpoint.iteration)
    results = await _execute_tools(
        [(call[0], call[1], call[2]) for call in checkpoint.pending_calls],
        registry,
        state,
        dispatch,
    )
    for call_id, output in results:
        history.append({"role": "tool", "tool_call_id": call_id, "content": output})
    checkpoint.pending_calls = []
    await _save_loop(checkpoint, history, cfg)


async def _run_tool_calls(
    tool_calls: list[tuple[str, str, str]],
    history: MessageHistory,
    registry: ToolRegistry,
    state: Any,
    cfg: ToolExecutionConfig,
    assistant_tool_calls_payload: list[dict],
    checkpoint: LoopCheckpoint,
    content: str | None = None,
) -> None:
    history.append(_assistant_tool_message(assistant_tool_calls_payload, content=content))
    checkpoint.pending_calls = [list(call) for call in tool_calls]
    await _save_loop(checkpoint, history, cfg)  # durable before approval/dispatch
    await _finish_pending(checkpoint, history, registry, state, cfg)


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
    try:
        while True:
            try:
                if normalized_timeout:
                    chunk = await asyncio.wait_for(iterator.__anext__(), normalized_timeout)
                else:
                    chunk = await iterator.__anext__()
            except StopAsyncIteration:
                return
            yield chunk
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()


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


@asynccontextmanager
async def _loop_session(
    registry: ToolRegistry,
    tool_names: list[str],
    tool_config: ToolExecutionConfig | None,
) -> AsyncIterator[tuple[ToolExecutionConfig, list[str]]]:
    """Manage lifecycle of loop configuration, runtime ownership, and artifact store."""
    cfg, owned_runtime = _resolve_tool_config(tool_config)
    effective_tool_names = list(tool_names)
    cfg = _setup_artifact_projection(registry, effective_tool_names, cfg)
    cfg = replace(cfg, allowed_tool_names=frozenset(effective_tool_names))
    token = _active_artifact_store.set(cfg.artifact_store)
    try:
        yield cfg, effective_tool_names
    finally:
        _active_artifact_store.reset(token)
        if owned_runtime is not None:
            await owned_runtime.close()


def _normalize_registry_and_tools(
    registry: ToolRegistry | None,
    tool_names: Sequence[str] | None,
    tools: Sequence[Callable[..., Any] | ToolDef] | ToolRegistry | None,
) -> tuple[ToolRegistry, list[str]]:
    """Normalize registry, tool_names, and tools inputs into a ToolRegistry and list of names."""
    if registry is None:
        if isinstance(tools, ToolRegistry):
            registry = tools
        elif tools is not None:
            registry = ToolRegistry(tools)
        else:
            registry = ToolRegistry()

    names = list(tool_names) if tool_names is not None else list(registry.names())
    return registry, names


class _GenerateAsStream:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model = inner.model
        self.timeout = getattr(inner, "timeout", None)
        self.retry_max_elapsed = getattr(inner, "retry_max_elapsed", None)

    async def astream(self, **kwargs: Any) -> AsyncIterator[Any]:
        async def iterate() -> AsyncIterator[Any]:
            response = await self.inner.generate(**kwargs)
            if not response.choices:
                raise ValueError("Provider returned no choices")
            message = response.choices[0].message
            calls = [
                SimpleNamespace(index=index, id=call.id, function=call.function)
                for index, call in enumerate(message.tool_calls or [])
            ]
            yield SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=message.content, tool_calls=calls)
                    )
                ],
                usage=getattr(response, "usage", None),
            )

        return iterate()


async def agent_loop(
    llm: GenerateLLM,
    *,
    system: str,
    context: str,
    registry: ToolRegistry | None = None,
    tool_names: Sequence[str] | None = None,
    tools: Sequence[Callable[..., Any] | ToolDef] | ToolRegistry | None = None,
    state: Any = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tool_config: ToolExecutionConfig | None = None,
    context_items: Sequence[ContextItem] = (),
) -> LoopResult:
    """Non-streamed presentation of the same checkpoint-aware execution engine."""
    async with aclosing(
        agent_loop_stream(
            _GenerateAsStream(llm),
            system=system,
            context=context,
            registry=registry,
            tool_names=tool_names,
            tools=tools,
            state=state,
            max_iterations=max_iterations,
            tool_config=tool_config,
            context_items=context_items,
        )
    ) as stream:
        async for item in stream:
            if isinstance(item, LoopResult):
                return item
    raise RuntimeError("Agent engine ended without a final result")


async def agent_loop_stream(
    llm: StreamingLLM,
    *,
    system: str,
    context: str,
    registry: ToolRegistry | None = None,
    tool_names: Sequence[str] | None = None,
    tools: Sequence[Callable[..., Any] | ToolDef] | ToolRegistry | None = None,
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
    effective_registry, effective_names = _normalize_registry_and_tools(registry, tool_names, tools)
    async with _loop_session(effective_registry, effective_names, tool_config) as (
        cfg,
        effective_tool_names,
    ):
        with tracer.start_as_current_span("agent_loop") as loop_span:
            with retry_budget(getattr(llm, "retry_max_elapsed", None)):
                loop_span.set_attribute("gen_ai.system", "litellm")
                loop_span.set_attribute("gen_ai.request.model", llm.model)
                loop_span.set_attribute("gen_ai.operation.name", "chat")
                loop_span.set_attribute("lughus.max_iterations", max_iterations)
                loop_span.set_attribute("lughus.streaming", True)

                history, tools_payload, prefix_len = _prepare_loop(
                    system,
                    context,
                    effective_registry,
                    effective_tool_names,
                    cfg,
                    context_items,
                )

                if max_iterations <= 0:
                    raise ValueError("max_iterations must be positive")
                checkpoint = cfg.loop_state if cfg.loop_state is not None else LoopCheckpoint()
                checkpoint.prefix_len = prefix_len
                if checkpoint.result is not None:
                    result_data = dict(checkpoint.result)
                    yield LoopResult(result_data.pop("text"), **result_data)
                    return
                await _save_loop(checkpoint, history, cfg)
                if checkpoint.pending_calls:
                    await _finish_pending(checkpoint, history, effective_registry, state, cfg)
                t0 = time.perf_counter()
                prompt_tokens = checkpoint.prompt_tokens
                completion_tokens = checkpoint.completion_tokens
                cached_tokens = checkpoint.cached_tokens

                for iteration in range(checkpoint.iteration, max_iterations):
                    _prune_if_needed(history, cfg, prefix_len, llm.model)
                    content_parts: list[str] = []
                    tc_map: dict[int, dict[str, str]] = {}

                    with tracer.start_as_current_span("llm.generate") as llm_span:
                        llm_span.set_attribute("gen_ai.request.model", llm.model)
                        llm_span.set_attribute("lughus.iteration", iteration + 1)

                        stream = await llm.astream(messages=history.view, tools=tools_payload)
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
                    checkpoint.iteration = iteration + 1
                    checkpoint.prompt_tokens = prompt_tokens
                    checkpoint.completion_tokens = completion_tokens
                    checkpoint.cached_tokens = cached_tokens

                    if not tc_map:
                        if streaming_mode_normalized == "buffered":
                            for content in content_parts:
                                yield StreamChunk(content=content)
                        result = _finalize_loop(
                            loop_span,
                            full_content,
                            iteration,
                            t0,
                            prompt_tokens,
                            completion_tokens,
                            cached_tokens,
                            llm.model,
                        )
                        checkpoint.result = {
                            "text": str(result),
                            "iterations": result.iterations,
                            "elapsed": result.elapsed,
                            "prompt_tokens": result.prompt_tokens,
                            "completion_tokens": result.completion_tokens,
                            "cached_tokens": result.cached_tokens,
                        }
                        await _save_loop(checkpoint, history, cfg)
                        yield result
                        return

                    sorted_tcs = [tc_map[i] for i in sorted(tc_map)]
                    assistant_tool_payload, tc_inputs = _format_tool_calls(sorted_tcs)

                    await _run_tool_calls(
                        tc_inputs,
                        history,
                        effective_registry,
                        state,
                        cfg,
                        assistant_tool_payload,
                        checkpoint,
                        content=full_content,
                    )

                loop_span.set_status(StatusCode.ERROR, "max iterations exceeded")
                raise LoopLimitError(f"Agent loop exceeded {max_iterations} iterations")
