from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator, ValidationError  # type: ignore[import-untyped]
from opentelemetry.trace import StatusCode

from ..core.artifacts import _summarize
from ..core.errors import (
    ApprovalRequired,
    ApprovalRequiredGroup,
    SafeToolError,
    ToolExecutionError,
    ToolTimeoutError,
    ToolValidationError,
)
from ..engine.tools import ConcurrencyMode, ToolRegistry
from ..governance.approval import ApprovalRequest, proposal_digest
from ..governance.budget import BudgetAmount
from ..governance.idempotency import AttemptStatus, ExecutionAttempt, IdempotencyKey
from ..governance.policy import DecisionKind, ToolProposal
from ..infra.telemetry import meter, tracer
from ._config import ToolExecutionConfig

if TYPE_CHECKING:
    from ..infra.runtime import ExecutionRuntime

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
# cache-specific counters for provider prefix caching visibility.
_cache_read_counter = meter.create_counter(
    "lughus.loop.cache_read_tokens",
    description="Cache-read input tokens reported by the LLM provider",
)
_cache_creation_counter = meter.create_counter(
    "lughus.loop.cache_creation_tokens",
    description="Cache-creation input tokens reported by the LLM provider",
)

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


def _record_llm_usage(span: Any, usage: Any, model: str) -> tuple[int, int, int]:
    """Extract usage from an LLM response and record on span + metrics.

    Also records ``lughus.loop.cache_read_tokens`` and
    ``lughus.loop.cache_creation_tokens`` counters and sets corresponding
    span attributes when the provider reports cache-related fields.
    """
    p, c, ca = _extract_usage(usage)
    span.set_attribute("gen_ai.system", "litellm")
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.usage.input_tokens", p)
    span.set_attribute("gen_ai.usage.output_tokens", c)
    if ca:
        span.set_attribute("gen_ai.usage.cached_tokens", ca)
    attrs = {"gen_ai.request.model": model}
    _token_counter.add(p, {**attrs, "lughus.token.type": "prompt"})
    _token_counter.add(c, {**attrs, "lughus.token.type": "completion"})
    if ca:
        _token_counter.add(ca, {**attrs, "lughus.token.type": "cached"})
    # cache-specific telemetry
    if ca:
        _cache_read_counter.add(ca, attrs)
        span.set_attribute("gen_ai.usage.cache_read_input_tokens", ca)
    cache_creation = _usage_get(usage, "cache_creation_input_tokens", 0) or 0
    if cache_creation:
        _cache_creation_counter.add(cache_creation, attrs)
        span.set_attribute("gen_ai.usage.cache_creation_input_tokens", cache_creation)
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


_TRACEBACK_RE = re.compile(r"Traceback\b.*", re.DOTALL)
_PATH_RE = re.compile(r"(?:[A-Za-z]:[/\\]|[/\\])[\w.\-]+(?:[/\\][\w.\-]+)+")
_LUGHUS_RE = re.compile(r"lughus[/.][\w./]*")


def _sanitize_message(msg: str) -> str:
    """Strip stack traces, file paths, and internal module names from *msg*."""
    msg = _TRACEBACK_RE.sub("", msg).strip()
    msg = _PATH_RE.sub("<redacted>", msg)
    msg = _LUGHUS_RE.sub("<internal>", msg)
    return msg or "An error occurred"


def _fix_hint(exc: Exception) -> tuple[bool, str]:
    """Return ``(retryable, fix)`` per the tool-result error contract."""
    if isinstance(exc, ToolTimeoutError):
        return True, "Retry with simpler input or increase timeout"
    if isinstance(exc, ToolValidationError):
        return True, "Correct the arguments and retry"
    if isinstance(exc, SafeToolError):
        return (
            bool(exc.retryable),
            "Retry the operation" if exc.retryable else "Try an alternative approach",
        )
    if isinstance(exc, ToolExecutionError):
        return False, "Try an alternative approach"
    return False, "Report the error to the user"


def _error_payload(exc: Exception) -> str:
    """Return structured JSON error envelope for the LLM tool response."""
    safe = isinstance(exc, (SafeToolError, ToolValidationError, ToolTimeoutError))
    raw_message = str(exc) if safe else "Tool execution failed"
    message = _sanitize_message(raw_message)
    error_type = getattr(exc, "code", type(exc).__name__)
    retryable, fix = _fix_hint(exc)
    return json.dumps(
        {
            "ok": False,
            "error": error_type,
            "message": message,
            "retryable": retryable,
            "fix": fix,
        }
    )


def _success_payload(
    text: str,
    *,
    parsed: Any = None,
    truncated: bool = False,
    original_bytes: int = 0,
) -> str:
    """Wrap a successful tool output in the standard JSON envelope."""
    if parsed is None:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = text
    envelope: dict[str, Any] = {"ok": True, "result": parsed}
    if truncated:
        envelope["truncated"] = True
        envelope["original_bytes"] = original_bytes
    return json.dumps(envelope, ensure_ascii=False)


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


def _truncate_json(value: Any, max_chars: int) -> str:
    """Structurally truncate a parsed JSON value to fit within *max_chars* using binary search."""
    if isinstance(value, list):
        lo, hi = 0, len(value)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = json.dumps(value[:mid], ensure_ascii=False, default=str)
            if len(candidate) <= max_chars:
                lo = mid
            else:
                hi = mid - 1
        return json.dumps(value[:lo], ensure_ascii=False, default=str) if lo else "[]"
    if isinstance(value, dict):
        keys = list(value.keys())
        lo, hi = 0, len(keys)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            subset = {k: value[k] for k in keys[:mid]}
            candidate = json.dumps(subset, ensure_ascii=False, default=str)
            if len(candidate) <= max_chars:
                lo = mid
            else:
                hi = mid - 1
        return (
            json.dumps({k: value[k] for k in keys[:lo]}, ensure_ascii=False, default=str)
            if lo
            else "{}"
        )
    if isinstance(value, str):
        safe_len = max(0, max_chars - 20)
        return json.dumps(value[:safe_len] + " [TRUNCATED]", ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, default=str)[:max_chars]


def _validate_tool_output(
    name: str,
    output: Any,
    max_tool_output_chars: int,
    text: str | None = None,
) -> tuple[str, bool, int]:
    """Validate and possibly truncate tool output.

    Returns ``(text, truncated, original_bytes)`` where *truncated* is ``True``
    when the output exceeded *max_tool_output_chars* and was sliced.
    """
    if text is None:
        text = (
            output
            if isinstance(output, str)
            else json.dumps(output, ensure_ascii=False, default=str)
        )
    original_bytes = len(text.encode("utf-8"))
    if max_tool_output_chars > 0 and len(text) > max_tool_output_chars:
        if not isinstance(output, str):
            text = _truncate_json(output, max_tool_output_chars)
        else:
            try:
                parsed = json.loads(text)
                text = _truncate_json(parsed, max_tool_output_chars)
            except (json.JSONDecodeError, ValueError):
                text = text[:max_tool_output_chars] + " [TRUNCATED]"
        return text, True, original_bytes
    return text, False, original_bytes


def _normalize_tool_error(
    exc: BaseException, name: str, timeout: float | None
) -> tuple[Exception, str, str, bool]:
    """Return (wrapped_exc, error_type, metric_error_type, needs_unknown_reconciliation)."""
    if isinstance(exc, ToolTimeoutError):
        return exc, type(exc).__name__, "timeout", False
    if isinstance(exc, TimeoutError):
        timeout_exc = ToolTimeoutError(f"Tool '{name}' timed out after {timeout}s")
        return timeout_exc, type(timeout_exc).__name__, "timeout", False
    if isinstance(exc, ToolValidationError):
        return exc, type(exc).__name__, "validation", True
    wrapped = (
        exc
        if isinstance(exc, (SafeToolError, ToolExecutionError))
        else ToolExecutionError(f"Tool '{name}' failed")
    )
    return wrapped, type(wrapped).__name__, "exception", True


def _runtime_of(cfg: ToolExecutionConfig) -> ExecutionRuntime:
    """Return the config's runtime, relying on the invariant _execute_tools enforces.

    The runtime is guaranteed non-None from _execute_tools onwards. That is
    why the two union-attr type-ignore markers and the redundant
    ``if cfg.runtime is not None`` guard could be removed outright rather than moved.
    """
    runtime = cfg.runtime
    if runtime is None:  # pragma: no cover - the entry point already refuses this
        raise RuntimeError(
            "ToolExecutionConfig carries no ExecutionRuntime; call tools through "
            "agent_loop()/agent_loop_stream()."
        )
    return runtime


async def _invoke_tool_callable(
    fn: Any,
    is_async: bool,
    state: dict,
    args: dict,
    cfg: ToolExecutionConfig,
    timeout: float | None,
) -> Any:
    if is_async:
        call: Any = fn(state=state, **args)
    else:
        call = _runtime_of(cfg).run_sync(lambda: fn(state=state, **args))
    return await asyncio.wait_for(call, timeout=timeout) if timeout else await call


async def _execute_tools(
    tool_calls: list[tuple[str, str, str]],
    registry: ToolRegistry,
    state: Any,
    config: ToolExecutionConfig | None = None,
) -> list[tuple[str, str]]:
    """Execute tool calls in parallel using ``asyncio.TaskGroup``.

    For a single tool call, executes directly without ``TaskGroup`` overhead.

    Each call is wrapped in an OTel span (``tool.{name}``).

    Edge cases:

    - **Unknown tool**: returns ``{"error": "Unknown tool: <name>"}`` as JSON.
    - **Tool exception**: catches the exception, records it on the OTel span
      with ``StatusCode.ERROR``, increments ``lughus.tool.errors``, and returns
      ``{"error": "<message>"}`` as JSON. Does **not** propagate.
    - **Empty args**: ``raw_args=""`` is treated as an empty dict.
    """

    # _execute_tools no longer manufactures a config, because doing so used
    # to allocate an ExecutionRuntime (and a thread pool) that nothing ever closed.
    # A missing runtime here is a programming error, not an opportunity to leak one.
    if config is None or config.runtime is None:
        raise RuntimeError(
            "_execute_tools requires a ToolExecutionConfig carrying an ExecutionRuntime. "
            "Call it through agent_loop()/agent_loop_stream(), or inject "
            "ToolExecutionConfig(runtime=ExecutionRuntime()) explicitly."
        )
    cfg = config
    max_parallel = max(1, cfg.max_parallel_tools)
    timeout = cfg.tool_timeout if cfg.tool_timeout and cfg.tool_timeout > 0 else None
    semaphore = asyncio.Semaphore(max_parallel)

    async def _run_unbounded(tc_id: str, name: str, raw_args: str) -> tuple[str, str]:
        started_at = time.perf_counter()
        _emit_tool_event(
            {"type": "tool_start", "tool_call_id": tc_id, "tool_name": name, "arguments": raw_args}
        )
        tool = registry.get_tool(name)
        if tool is None:
            unknown_exc = ToolValidationError(f"Unknown tool: {name}")
            output = _error_payload(unknown_exc)
            _emit_tool_event(
                {
                    "type": "tool_result",
                    "tool_call_id": tc_id,
                    "tool_name": name,
                    "status": "error",
                    "error_type": type(unknown_exc).__name__,
                    "output": output,
                    "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                }
            )
            return tc_id, output

        fn = tool.fn
        with tracer.start_as_current_span(f"tool.{name}") as span:
            span.set_attribute("lughus.tool.name", name)
            span.set_attribute("lughus.tool.timeout_s", timeout or 0)
            status, error_type = "ok", None
            idem_key: IdempotencyKey | None = None
            budget_reservation: str | None = None
            try:
                args = _validate_tool_args(
                    name=name,
                    raw_args=raw_args,
                    validator=tool.validator,
                    max_tool_args_chars=cfg.max_tool_args_chars,
                )
                # ── Step 1: Policy ──────────────────────────────────
                decision = None
                if cfg.policy is not None:
                    if cfg.principal is None:
                        raise ToolExecutionError(
                            "A principal is required when tool policy is enabled"
                        )
                    proposal = ToolProposal(
                        run_id=cfg.run_id,
                        tool_name=name,
                        arguments=args,
                        effects=frozenset(effect.value for effect in tool.effects),
                        risk=tool.risk.value,
                        required_scopes=tool.required_scopes,
                    )
                    decision = await cfg.policy.evaluate(proposal, cfg.principal)
                    if decision.kind == DecisionKind.DENY:
                        raise ToolExecutionError(f"Tool policy denied action: {decision.code}")

                # ── Step 2: Receipt lookup ──────────────────────────
                if cfg.idempotency_store is not None and tool.idempotent:
                    check_key = IdempotencyKey.from_args(cfg.run_id, name, args)
                    existing_completed = await cfg.idempotency_store.get(check_key)
                    if (
                        existing_completed is not None
                        and existing_completed.status == AttemptStatus.COMPLETED
                    ):
                        output = existing_completed.result or ""
                        span.set_attribute("lughus.tool.idempotent_hit", True)
                        span.set_status(StatusCode.OK)
                        _emit_tool_event(
                            {
                                "type": "tool_result",
                                "tool_call_id": tc_id,
                                "tool_name": name,
                                "status": "ok",
                                "output": output,
                                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                                "idempotent_hit": True,
                            }
                        )
                        return tc_id, output

                # ── Step 3: Approval (check/create, WITHOUT consuming)
                approval_to_consume: ApprovalRequest | None = None
                if (
                    decision is not None and decision.kind == DecisionKind.REQUIRE_APPROVAL
                ) or tool.requires_approval:
                    if cfg.approval_store is None:
                        raise ApprovalRequired("unknown", name)
                    digest = proposal_digest(name, args)
                    request = await cfg.approval_store.find(cfg.run_id, digest)
                    if request is not None and request.status.value == "approved":
                        approval_to_consume = request
                    elif request is not None and request.status.value == "rejected":
                        raise ToolExecutionError("Human approval was rejected")
                    else:
                        if request is None:
                            request = ApprovalRequest(
                                run_id=cfg.run_id,
                                tool_name=name,
                                proposal_hash=digest,
                                risk=tool.risk.value,
                            )
                            await cfg.approval_store.create(request)
                        raise ApprovalRequired(request.request_id, name, request.expires_at)

                # ── Step 4: Claim ───────────────────────────────────
                if cfg.idempotency_store is not None and tool.idempotent:
                    idem_key = IdempotencyKey.from_args(cfg.run_id, name, args)
                    existing = await cfg.idempotency_store.claim(
                        ExecutionAttempt(key=idem_key, status=AttemptStatus.PENDING)
                    )
                    if existing is not None and existing.status == AttemptStatus.COMPLETED:
                        output = existing.result or ""
                        span.set_attribute("lughus.tool.idempotent_hit", True)
                        span.set_status(StatusCode.OK)
                        _emit_tool_event(
                            {
                                "type": "tool_result",
                                "tool_call_id": tc_id,
                                "tool_name": name,
                                "status": "ok",
                                "output": output,
                                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
                                "idempotent_hit": True,
                            }
                        )
                        return tc_id, output
                    if existing is not None:
                        raise ToolExecutionError("An idempotent execution is already in progress")

                # ── Step 5: Slots ───────────────────────────────────
                slot = _runtime_of(cfg).tool_slot(cfg.tool_queue_timeout)
                async with slot:
                    # ── Step 6: Budget ──────────────────────────────
                    if cfg.budget is not None:
                        budget_reservation = await cfg.budget.reserve(BudgetAmount(tool_calls=1))
                    # ── Step 7: Consumption ─────────────────────────
                    if approval_to_consume is not None and cfg.approval_store is not None:
                        await cfg.approval_store.consume(approval_to_consume.request_id)
                    # ── Step 8: Dispatch ────────────────────────────
                    mode = tool.concurrency
                    if mode == ConcurrencyMode.GLOBAL_EXCLUSIVE:
                        async with _runtime_of(cfg).global_exclusive_lock:
                            output = await _invoke_tool_callable(
                                fn, tool.is_async, state, args, cfg, timeout
                            )
                    elif mode == ConcurrencyMode.SERIAL_PER_TOOL:
                        async with _runtime_of(cfg).resource_slot(name):
                            output = await _invoke_tool_callable(
                                fn, tool.is_async, state, args, cfg, timeout
                            )
                    elif mode == ConcurrencyMode.SERIAL_PER_RESOURCE:
                        rk = f"{name}:{tool.resource_key(args)}"  # type: ignore[misc]
                        async with _runtime_of(cfg).resource_slot(rk):
                            output = await _invoke_tool_callable(
                                fn, tool.is_async, state, args, cfg, timeout
                            )
                    else:
                        # PARALLEL_SAFE — no lock
                        output = await _invoke_tool_callable(
                            fn, tool.is_async, state, args, cfg, timeout
                        )
                if tool.output_validator is not None:
                    validation_errors = sorted(
                        tool.output_validator.iter_errors(output),
                        key=lambda error: list(error.path),
                    )
                    if validation_errors:
                        raise ToolValidationError(
                            f"Tool '{name}' returned an invalid result: "
                            f"{validation_errors[0].message}"
                        )
                is_str = isinstance(output, str)
                text = output if is_str else json.dumps(output, ensure_ascii=False, default=str)
                original_bytes = len(text.encode("utf-8"))
                parsed = None if is_str else output

                # Artifact projection FIRST — store full content before truncation.
                if (
                    cfg.artifact_projection
                    and cfg.artifact_store is not None
                    and len(text) > cfg.artifact_projection_threshold
                ):
                    full_payload = _success_payload(
                        text,
                        parsed=parsed,
                        truncated=False,
                        original_bytes=original_bytes,
                    )
                    artifact_id = cfg.artifact_store.store_artifact(full_payload)
                    summary = _summarize(text)
                    output = json.dumps(
                        {
                            "ok": True,
                            "artifact_id": artifact_id,
                            "summary": summary,
                            "hint": "Use fetch_artifact to retrieve full content",
                        },
                        ensure_ascii=False,
                    )
                else:
                    text, truncated, original_bytes = _validate_tool_output(
                        name=name,
                        output=output,
                        max_tool_output_chars=cfg.max_tool_output_chars,
                        text=text,
                    )
                    output = _success_payload(
                        text,
                        parsed=parsed if not truncated else None,
                        truncated=truncated,
                        original_bytes=original_bytes,
                    )
                if idem_key is not None and cfg.idempotency_store is not None:
                    await cfg.idempotency_store.save(
                        ExecutionAttempt(
                            key=idem_key, status=AttemptStatus.COMPLETED, result=output
                        )
                    )
                span.set_status(StatusCode.OK)
            except ApprovalRequired:
                raise  # propagate to task wrapper — not a tool error
            except Exception as exc:  # noqa: BLE001 — boundary guard: tools execute arbitrary user code
                wrapped, error_type, metric_type, needs_reconcile = _normalize_tool_error(
                    exc, name, timeout
                )
                span.set_status(StatusCode.ERROR, str(wrapped))
                if metric_type == "exception":
                    span.record_exception(exc)
                _tool_errors.add(1, {"lughus.tool.name": name, "lughus.error.type": metric_type})
                if idem_key is not None and cfg.idempotency_store is not None and needs_reconcile:
                    await cfg.idempotency_store.save(
                        ExecutionAttempt(
                            key=idem_key,
                            status=AttemptStatus.OUTCOME_UNKNOWN,
                            error="reconciliation required",
                        )
                    )
                output, status = _error_payload(wrapped), "error"
            finally:
                if budget_reservation is not None and cfg.budget is not None:
                    await cfg.budget.settle(budget_reservation, BudgetAmount(tool_calls=1))
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
        try:
            return [await _run(*tool_calls[0])]
        except ApprovalRequired as e:
            raise ApprovalRequiredGroup([e]) from e

    results: list[tuple[str, str] | None] = [None] * len(tool_calls)
    approval_errors: list[ApprovalRequired] = []

    async def _task(idx: int, tc_id: str, name: str, raw_args: str) -> None:
        try:
            results[idx] = await _run(tc_id, name, raw_args)
        except ApprovalRequired as e:
            approval_errors.append(e)

    try:
        async with asyncio.TaskGroup() as tg:
            for idx, (tc_id, name, raw_args) in enumerate(tool_calls):
                tg.create_task(_task(idx, tc_id, name, raw_args))
    except ExceptionGroup as eg:
        raise eg.exceptions[0] from eg

    if approval_errors:
        raise ApprovalRequiredGroup(approval_errors)
    return [r for r in results if r is not None]
