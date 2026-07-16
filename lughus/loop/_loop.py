from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, AsyncGenerator, AsyncIterator

from opentelemetry.trace import StatusCode

from ..errors import LoopLimitError
from ..llm import _RETRYABLE_ERRORS, _retry_after_seconds
from ..retry import _retry_budget_var, _retry_used_var, retry_budget
from ..telemetry import tracer
from ..tools import ToolRegistry
from ._config import DEFAULT_MAX_ITERATIONS, ToolExecutionConfig
from ._result import LoopResult
from ._execute import (
    _check_message_history_size,
    _record_llm_usage,
    _assistant_tool_message,
    _execute_tools,
    _loop_duration,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..llm import GenerateLLM, StreamingLLM


def _prepare_loop(
    system: str,
    context: str,
    registry: ToolRegistry,
    tool_names: list[str],
    cfg: ToolExecutionConfig,
) -> tuple[list[dict], list[dict]]:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": context},
    ]
    tools = registry.declarations(
        tool_names,
        strict=True,
        compact=cfg.compact_tool_schemas,
    )
    return messages, tools


async def _run_tool_calls(
    tool_calls: list[tuple[str, str, str]],
    messages: list[dict],
    registry: ToolRegistry,
    state: Any,
    cfg: ToolExecutionConfig,
    assistant_tool_calls_payload: list[dict],
    content: str | None = None,
) -> None:
    messages.append(
        _assistant_tool_message(
            assistant_tool_calls_payload,
            content=content,
        )
    )
    results = await _execute_tools(tool_calls, registry, state, cfg)
    for tc_id, output in results:
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": output,
        })


def _finalize_loop(
    span,
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
    span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
    span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
    span.set_attribute("gen_ai.usage.cached_tokens", cached_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", result.total_tokens)
    span.set_status(StatusCode.OK)
    _loop_duration.record(elapsed, {"gen_ai.request.model": model})
    return result


async def _stream_with_timeout(stream: AsyncIterator[Any], timeout: float | None) -> AsyncIterator[Any]:
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
) -> LoopResult:
    """Run an agentic loop until the LLM produces a text response.

    Returns a :class:`LoopResult` — a ``str`` subclass with attached usage
    metadata (``iterations``, ``elapsed``, ``prompt_tokens``,
    ``completion_tokens``, ``cached_tokens``, ``total_tokens``).
    """
    cfg = tool_config or ToolExecutionConfig()
    with tracer.start_as_current_span("agent_loop") as loop_span:
        with retry_budget(getattr(llm, "retry_max_elapsed", None)):
            loop_span.set_attribute("gen_ai.request.model", llm.model)
            loop_span.set_attribute("lughus.max_iterations", max_iterations)

            messages, tools = _prepare_loop(system, context, registry, tool_names, cfg)

            t0 = time.perf_counter()
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0

            for iteration in range(max_iterations):
                _check_message_history_size(messages, cfg)
                with tracer.start_as_current_span("llm.generate") as llm_span:
                    llm_span.set_attribute("gen_ai.request.model", llm.model)
                    llm_span.set_attribute("lughus.iteration", iteration + 1)
                    response = await llm.generate(messages=messages, tools=tools)

                    if hasattr(response, "usage") and response.usage:
                        p, c, ca = _record_llm_usage(
                            llm_span, response.usage, llm.model,
                        )
                        prompt_tokens += p
                        completion_tokens += c
                        cached_tokens += ca

                msg = response.choices[0].message

                if not msg.tool_calls:
                    return _finalize_loop(
                        loop_span, msg.content or "", iteration, t0,
                        prompt_tokens, completion_tokens, cached_tokens,
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
                    messages,
                    registry,
                    state,
                    cfg,
                    assistant_tool_payload,
                    content=msg.content,
                )

            loop_span.set_status(StatusCode.ERROR, "max iterations exceeded")
            raise LoopLimitError(f"Agent loop exceeded {max_iterations} iterations")


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
) -> AsyncGenerator[str | LoopResult, None]:
    """Streaming variant of :func:`agent_loop`.

    Yields text chunks as the LLM generates them. The **last** yielded value
    is always a :class:`LoopResult` (a ``str`` subclass with usage metadata).
    """
    cfg = tool_config or ToolExecutionConfig()
    with tracer.start_as_current_span("agent_loop") as loop_span:
        with retry_budget(getattr(llm, "retry_max_elapsed", None)):
            loop_span.set_attribute("gen_ai.request.model", llm.model)
            loop_span.set_attribute("lughus.max_iterations", max_iterations)
            loop_span.set_attribute("lughus.streaming", True)

            messages, tools = _prepare_loop(system, context, registry, tool_names, cfg)

            t0 = time.perf_counter()
            prompt_tokens = 0
            completion_tokens = 0
            cached_tokens = 0

            for iteration in range(max_iterations):
                _check_message_history_size(messages, cfg)
                content_parts: list[str] = []
                tc_map: dict[int, dict[str, str]] = {}

                max_retries = getattr(llm, "max_retries", 0)
                retry_base_delay = getattr(llm, "retry_base_delay", 1.0)
                retry_max_elapsed = getattr(llm, "retry_max_elapsed", None)
                timeout = getattr(llm, "timeout", None)

                for attempt in range(max_retries + 1):
                    content_parts.clear()
                    tc_map.clear()
                    try:
                        with tracer.start_as_current_span("llm.generate") as llm_span:
                            llm_span.set_attribute("gen_ai.request.model", llm.model)
                            llm_span.set_attribute("lughus.iteration", iteration + 1)

                            stream = await llm.astream(messages=messages, tools=tools)
                            async for chunk in _stream_with_timeout(stream, timeout):
                                _usage_recorded = False

                                if not chunk.choices:
                                    if hasattr(chunk, "usage") and chunk.usage:
                                        p, c, ca = _record_llm_usage(
                                            llm_span, chunk.usage, llm.model,
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

                                if delta.tool_calls:
                                    for tc_delta in delta.tool_calls:
                                        idx = tc_delta.index
                                        if idx not in tc_map:
                                            tc_map[idx] = {"id": "", "name": "", "arguments": ""}
                                        if tc_delta.id:
                                            tc_map[idx]["id"] = tc_delta.id
                                        if tc_delta.function:
                                            if tc_delta.function.name:
                                                tc_map[idx]["name"] += tc_delta.function.name
                                            if tc_delta.function.arguments:
                                                tc_map[idx]["arguments"] += tc_delta.function.arguments

                                if not _usage_recorded and hasattr(chunk, "usage") and chunk.usage:
                                    p, c, ca = _record_llm_usage(
                                        llm_span, chunk.usage, llm.model,
                                    )
                                    prompt_tokens += p
                                    completion_tokens += c
                                    cached_tokens += ca
                        break
                    except _RETRYABLE_ERRORS as exc:
                        if attempt >= max_retries:
                            raise
                        retry_after = _retry_after_seconds(exc)
                        if retry_after is not None:
                            delay = retry_after
                        else:
                            raw_delay = retry_base_delay * (2 ** attempt)
                            delay = random.uniform(0.0, raw_delay) if raw_delay > 0 else 0.0

                        budget = _retry_budget_var.get()
                        retry_sleep_elapsed = _retry_used_var.get()
                        if budget is None:
                            budget = retry_max_elapsed
                        if budget is not None and retry_sleep_elapsed + delay > budget:
                            raise
                        _retry_used_var.set(retry_sleep_elapsed + delay)

                        _logger.warning(
                            "LLM.astream: transient error (%s) during chunk streaming, retry %d/%d in %.1fs",
                            type(exc).__name__, attempt + 1, max_retries, delay,
                        )
                        await asyncio.sleep(delay)

                full_content = "".join(content_parts)

                if not tc_map:
                    for content in content_parts:
                        yield content
                    yield _finalize_loop(
                        loop_span, full_content, iteration, t0,
                        prompt_tokens, completion_tokens, cached_tokens,
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
                tc_inputs = [
                    (tc["id"], tc["name"], tc["arguments"]) for tc in sorted_tcs
                ]

                await _run_tool_calls(
                    tc_inputs,
                    messages,
                    registry,
                    state,
                    cfg,
                    assistant_tool_payload,
                    content=full_content,
                )

            loop_span.set_status(StatusCode.ERROR, "max iterations exceeded")
            raise LoopLimitError(f"Agent loop exceeded {max_iterations} iterations")
