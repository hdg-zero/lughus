from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import json
import logging
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from typing import Any, AsyncIterator

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from opentelemetry.trace import StatusCode

from ..errors import (
    LoopLimitError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from ..telemetry import meter, tracer
from .._threading import run_sync_in_thread
from ..tools import ToolRegistry
from ._config import ToolExecutionConfig

_logger = logging.getLogger(__name__)

# ── Metrics ─────────────────────────────────────────────

_token_counter = meter.create_counter(
    "lughus.loop.tokens",
    description="LLM tokens consumed",
)
_loop_duration = meter.create_histogram(
    "lughus.loop.duration",
    unit="s",
    description="Agent loop wall-clock duration",
)
_tool_errors = meter.create_counter(
    "lughus.tool.errors",
    description="Tool execution errors",
)

_GLOBAL_TOOL_LOCK = threading.Lock()
_GLOBAL_TOOL_SEMAPHORES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    asyncio.Semaphore,
] = weakref.WeakKeyDictionary()
_tool_event_sink: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = (
    contextvars.ContextVar("lughus_tool_event_sink", default=None)
)


def _usage_get(usage: Any, key: str, default: Any = 0) -> Any:
    if isinstance(usage, dict):
        return usage.get(key, default)
    return getattr(usage, key, default)


def _extract_usage(usage: Any) -> tuple[int, int, int]:
    """Return (prompt_tokens, completion_tokens, cached_tokens)."""
    prompt = _usage_get(usage, "prompt_tokens", 0) or 0
    completion = _usage_get(usage, "completion_tokens", 0) or 0
    cached = 0
    details = _usage_get(usage, "prompt_tokens_details", None)
    if details:
        cached += _usage_get(details, "cached_tokens", 0) or 0
    cached += _usage_get(usage, "_cache_read_input_tokens", 0) or 0
    return prompt, completion, cached


def _record_llm_usage(span, usage: Any, model: str) -> tuple[int, int, int]:
    """Extract usage from an LLM response and record on span + metrics."""
    p, c, ca = _extract_usage(usage)
    span.set_attribute("gen_ai.usage.prompt_tokens", p)
    span.set_attribute("gen_ai.usage.completion_tokens", c)
    if ca:
        span.set_attribute("gen_ai.usage.cached_tokens", ca)
    attrs = {"gen_ai.request.model": model}
    _token_counter.add(p, {**attrs, "token.type": "prompt"})
    _token_counter.add(c, {**attrs, "token.type": "completion"})
    if ca:
        _token_counter.add(ca, {**attrs, "token.type": "cached"})
    return p, c, ca


@contextlib.contextmanager
def collect_tool_events(sink: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    """Collect tool execution events emitted by the active agent loop context."""
    token = _tool_event_sink.set(sink)
    try:
        yield
    finally:
        _tool_event_sink.reset(token)


def _emit_tool_event(event: dict[str, Any]) -> None:
    sink = _tool_event_sink.get()
    if sink is None:
        return
    sink(event)


def _assistant_tool_message(
    tool_calls: list[dict[str, Any]],
    content: str | None = None,
) -> dict[str, Any]:
    """Build a provider-compatible assistant message containing tool calls."""
    message: dict[str, Any] = {
        "role": "assistant",
        "tool_calls": tool_calls,
    }
    if content:
        message["content"] = content
    return message


def _error_payload(exc: Exception) -> str:
    """Return structured JSON error content for the LLM tool response."""
    return json.dumps({
        "error": str(exc),
        "error_type": type(exc).__name__,
    })


def _validate_tool_args(
    *,
    name: str,
    raw_args: str,
    validator: Draft202012Validator,
    max_tool_args_chars: int,
) -> dict[str, Any]:
    if max_tool_args_chars > 0 and len(raw_args) > max_tool_args_chars:
        raise ToolValidationError(
            f"Arguments for tool '{name}' exceed {max_tool_args_chars} characters"
        )
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        raise ToolValidationError(f"Invalid JSON arguments for tool '{name}': {exc.msg}") from exc
    if not isinstance(args, dict):
        raise ToolValidationError(f"Arguments for tool '{name}' must be a JSON object")
    try:
        validator.validate(args)
    except ValidationError as exc:
        path = ".".join(str(p) for p in exc.absolute_path)
        location = f" at '{path}'" if path else ""
        raise ToolValidationError(
            f"Invalid arguments for tool '{name}'{location}: {exc.message}"
        ) from exc
    return args


def _validate_tool_output(name: str, output: Any, max_tool_output_chars: int) -> str:
    text = (
        output
        if isinstance(output, str)
        else json.dumps(output, ensure_ascii=False, default=str)
    )
    if max_tool_output_chars > 0 and len(text) > max_tool_output_chars:
        raise ToolValidationError(
            f"Output from tool '{name}' exceeds {max_tool_output_chars} characters"
        )
    return text


def _message_history_chars(messages: list[dict]) -> int:
    return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))


def _check_message_history_size(messages: list[dict], config: ToolExecutionConfig) -> None:
    limit = config.max_message_history_chars
    if limit > 0 and _message_history_chars(messages) > limit:
        raise LoopLimitError(f"Agent message history exceeded {limit} characters")


def _global_tool_semaphore(max_global_tools: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _GLOBAL_TOOL_LOCK:
        semaphore = _GLOBAL_TOOL_SEMAPHORES.get(loop)
        if semaphore is None:
            initial_limit = max_global_tools if max_global_tools > 0 else 64
            semaphore = asyncio.Semaphore(initial_limit)
            _GLOBAL_TOOL_SEMAPHORES[loop] = semaphore
        return semaphore


@contextlib.asynccontextmanager
async def _acquire_global_tool_slot(
    max_global_tools: int,
    wait_timeout: float | None,
) -> AsyncIterator[None]:
    """Acquire one worker-local tool slot."""
    if max_global_tools <= 0:
        yield
        return

    semaphore = _global_tool_semaphore(max_global_tools)
    normalized_timeout = wait_timeout if wait_timeout and wait_timeout > 0 else 0.0
    acquired = False
    if normalized_timeout <= 0:
        if semaphore.locked():
            raise ToolTimeoutError("Timed out waiting for a global tool slot")
        await semaphore.acquire()
    else:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=normalized_timeout)
        except asyncio.TimeoutError as exc:
            raise ToolTimeoutError("Timed out waiting for a global tool slot") from exc
    acquired = True
    try:
        yield
    finally:
        if acquired:
            semaphore.release()


def _unwrap_async_target(fn: Callable[..., Any]) -> Any:
    target: Any = fn
    while isinstance(target, functools.partial):
        target = target.func
    return inspect.unwrap(target)


def _is_async_callable(fn: Callable[..., Any]) -> bool:
    """Return True for coroutine functions, decorated async functions, and async callables."""
    unwrapped = _unwrap_async_target(fn)
    if inspect.iscoroutinefunction(unwrapped):
        return True
    call = getattr(unwrapped, "__call__", None)
    return bool(call and inspect.iscoroutinefunction(_unwrap_async_target(call)))


async def _run_sync_tool(call, *, max_workers: int) -> Any:
    """Run a synchronous tool using the optimized process-wide thread pool."""
    return await run_sync_in_thread(call, max_workers=max_workers)


async def _execute_tools(
    tool_calls: list[tuple[str, str, str]],
    registry: ToolRegistry,
    state: Any,
    config: ToolExecutionConfig | None = None,
) -> list[tuple[str, str]]:
    """Execute tool calls in parallel using ``asyncio.gather()``.

    For a single tool call, executes directly without ``gather`` overhead.

    Each call is wrapped in an OTel span (``tool.{name}``).

    Edge cases:

    - **Unknown tool**: returns ``{"error": "Unknown tool: <name>"}`` as JSON.
    - **Tool exception**: catches the exception, records it on the OTel span
      with ``StatusCode.ERROR``, increments ``lughus.tool.errors``, and returns
      ``{"error": "<message>"}`` as JSON. Does **not** propagate.
    - **Empty args**: ``raw_args=""`` is treated as an empty dict.
    """

    cfg = config or ToolExecutionConfig()
    max_parallel = max(1, cfg.max_parallel_tools)
    timeout = cfg.tool_timeout if cfg.tool_timeout and cfg.tool_timeout > 0 else None
    semaphore = asyncio.Semaphore(max_parallel)

    async def _run_unbounded(tc_id: str, name: str, raw_args: str) -> tuple[str, str]:
        started_at = time.perf_counter()
        _emit_tool_event({
            "type": "tool_start",
            "tool_call_id": tc_id,
            "tool_name": name,
            "arguments": raw_args,
        })
        tool = registry.get_tool(name)
        if tool is None:
            unknown_exc = ToolValidationError(f"Unknown tool: {name}")
            output = _error_payload(unknown_exc)
            _emit_tool_event({
                "type": "tool_result",
                "tool_call_id": tc_id,
                "tool_name": name,
                "status": "error",
                "error_type": type(unknown_exc).__name__,
                "output": output,
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            })
            return tc_id, output
        fn = tool.fn
        with tracer.start_as_current_span(f"tool.{name}") as span:
            span.set_attribute("tool.name", name)
            span.set_attribute("tool.timeout_s", timeout or 0)
            status = "ok"
            error_type: str | None = None
            try:
                args = _validate_tool_args(
                    name=name,
                    raw_args=raw_args,
                    validator=tool.validator,
                    max_tool_args_chars=cfg.max_tool_args_chars,
                )
                async with _acquire_global_tool_slot(
                    cfg.max_global_tools,
                    cfg.tool_queue_timeout,
                ):
                    if _is_async_callable(fn):
                        call: Any = fn(state=state, **args)
                    else:
                        call = _run_sync_tool(
                            lambda: fn(state=state, **args),
                            max_workers=cfg.max_sync_thread_workers,
                        )
                    if timeout:
                        output = await asyncio.wait_for(call, timeout=timeout)
                    else:
                        output = await call
                output = _validate_tool_output(
                    name=name,
                    output=output,
                    max_tool_output_chars=cfg.max_tool_output_chars,
                )
                span.set_status(StatusCode.OK)
            except ToolTimeoutError as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                _tool_errors.add(1, {"tool.name": name, "error.type": "timeout"})
                output = _error_payload(exc)
                status = "error"
                error_type = type(exc).__name__
            except asyncio.TimeoutError:
                timeout_exc = ToolTimeoutError(f"Tool '{name}' timed out after {timeout}s")
                span.set_status(StatusCode.ERROR, str(timeout_exc))
                _tool_errors.add(1, {"tool.name": name, "error.type": "timeout"})
                output = _error_payload(timeout_exc)
                status = "error"
                error_type = type(timeout_exc).__name__
            except ToolValidationError as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                _tool_errors.add(1, {"tool.name": name, "error.type": "validation"})
                output = _error_payload(exc)
                status = "error"
                error_type = type(exc).__name__
            except Exception as exc:
                wrapped = ToolExecutionError(f"Tool '{name}' failed: {exc}")
                span.set_status(StatusCode.ERROR, str(wrapped))
                span.record_exception(exc)
                _tool_errors.add(1, {"tool.name": name, "error.type": "exception"})
                output = _error_payload(wrapped)
                status = "error"
                error_type = type(wrapped).__name__
        event: dict[str, Any] = {
            "type": "tool_result",
            "tool_call_id": tc_id,
            "tool_name": name,
            "status": status,
            "output": output,
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }
        if error_type:
            event["error_type"] = error_type
        _emit_tool_event(event)
        return tc_id, output

    async def _run(tc_id: str, name: str, raw_args: str) -> tuple[str, str]:
        async with semaphore:
            return await _run_unbounded(tc_id, name, raw_args)

    if len(tool_calls) == 1:
        return [await _run(*tool_calls[0])]
    return list(await asyncio.gather(*(_run(*tc) for tc in tool_calls)))
