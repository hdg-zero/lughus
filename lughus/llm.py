"""LLM client — thin wrapper around LiteLLM."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any, Protocol, cast

import litellm

from .errors import LLMResponseError
from .retry import _retry_budget_var, _retry_used_var, retry_budget
from .telemetry import meter

_logger = logging.getLogger(__name__)

__all__ = ["LLM", "GenerateLLM", "StreamingLLM", "retry_budget"]


class GenerateLLM(Protocol):
    """Structural protocol for non-streaming LLM clients accepted by agent_loop()."""

    model: str

    async def generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> litellm.ModelResponse: ...


class StreamingLLM(Protocol):
    """Structural protocol for streaming LLM clients accepted by agent_loop_stream()."""

    model: str
    timeout: float | None

    async def astream(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> AsyncIterator[Any]: ...


# Transient errors that are safe to retry.
_RETRYABLE_ERRORS = (
    LLMResponseError,
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.APIConnectionError,
    TimeoutError,
)

_retry_counter = meter.create_counter(
    "lughus.llm.retries",
    description="LLM retry attempts",
)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extract Retry-After seconds from common exception shapes."""
    headers = getattr(exc, "headers", None)
    response = getattr(exc, "response", None)
    if headers is None and response is not None:
        headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class LLM:
    """Async LLM client. Delegates to ``litellm.acompletion()``.

    Args:
        model: LiteLLM model string (e.g. ``"openai/gpt-4o"``). Required.
        max_output_tokens: Max tokens in the LLM response (default: 16384).
        timeout: Seconds before an LLM call raises ``asyncio.TimeoutError``.
            Set to ``None`` to disable (useful for slow local models).
            Controlled via the ``LLM_TIMEOUT`` env var when using
            :class:`~lughus.BaseSettings` (default: 120s).
        max_retries: Number of retries on transient errors (``RateLimitError``,
            ``ServiceUnavailableError``, ``APIConnectionError``, and call
            timeouts). Default: 3. Set to 0 to disable retries. Controlled via
            ``LLM_MAX_RETRIES``.
        retry_base_delay: Base delay in seconds for exponential backoff.
            Delay for attempt N is ``retry_base_delay * 2**N``. Default: 1.0s.
            Controlled via ``LLM_RETRY_BASE_DELAY``. Set to 0.0 in tests.
        retry_max_elapsed: Total retry sleep budget in seconds (default 60s).
            Set to ``None`` or ``0`` to disable the budget.
    """

    _RESERVED_KEYS = frozenset({"messages", "tools", "stream", "stream_options", "model"})

    def __init__(
        self,
        model: str,
        max_output_tokens: int = 16384,
        timeout: float | None = 120.0,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_elapsed: float | None = 60.0,
        params: Mapping[str, Any] | None = None,
    ):
        if not model:
            raise ValueError(
                "No model specified. Set the AGENT_MODEL environment variable "
                "(e.g. AGENT_MODEL=openai/gpt-4o) or pass model= explicitly."
            )
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout if (timeout and timeout > 0) else None
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_elapsed = (
            retry_max_elapsed if (retry_max_elapsed and retry_max_elapsed > 0) else None
        )
        if params:
            for key in params:
                if key in self._RESERVED_KEYS:
                    raise ValueError(
                        f"'{key}' is a reserved LLM parameter and cannot be overridden"
                    )
        self.params: Mapping[str, Any] = dict(params) if params else {}

    @classmethod
    def from_settings(cls, settings: Any) -> LLM:
        """Create an LLM using the common fields exposed by BaseSettings."""
        return cls(
            model=settings.model,
            max_output_tokens=settings.max_output_tokens,
            timeout=settings.llm_timeout,
            max_retries=settings.max_retries,
            retry_base_delay=settings.retry_base_delay,
            retry_max_elapsed=settings.retry_max_elapsed,
        )

    async def _with_retry(self, coro_factory: Callable[[], Any], label: str) -> Any:
        """Execute ``coro_factory()`` with exponential backoff on transient errors.

        Retries up to ``self.max_retries`` times on :data:`_RETRYABLE_ERRORS`.
        The delay before attempt N (0-indexed) is ``retry_base_delay * 2**N``.
        Non-retryable errors are re-raised immediately.
        """
        t0 = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                coro = coro_factory()
                return await (
                    asyncio.wait_for(coro, timeout=self.timeout) if self.timeout else coro
                )
            except _RETRYABLE_ERRORS as exc:
                if attempt >= self.max_retries:
                    raise
                retry_after = _retry_after_seconds(exc)
                if retry_after is not None:
                    delay = retry_after
                else:
                    raw_delay = self.retry_base_delay * (2**attempt)
                    delay = random.uniform(0.0, raw_delay) if raw_delay > 0 else 0.0
                budget = _retry_budget_var.get()
                retry_sleep_elapsed = _retry_used_var.get()
                if budget is None:
                    budget = self.retry_max_elapsed
                if budget is not None and retry_sleep_elapsed + delay > budget:
                    raise
                _retry_used_var.set(retry_sleep_elapsed + delay)
                _retry_counter.add(
                    1,
                    {
                        "gen_ai.request.model": self.model,
                        "error.type": type(exc).__name__,
                        "retry.label": label,
                    },
                )
                _logger.warning(
                    "%s: transient error (%s), retry %d/%d in %.1fs after %.1fs elapsed",
                    label,
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                    time.perf_counter() - t0,
                )
                await asyncio.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover

    async def generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> litellm.ModelResponse:
        """Send messages (and optional tool declarations) to the LLM."""

        async def _make() -> litellm.ModelResponse:
            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_output_tokens,
                **self.params,
            }
            if tools:
                kwargs["tools"] = tools
            response = cast(litellm.ModelResponse, await litellm.acompletion(**kwargs))
            if not getattr(response, "choices", None):
                raise LLMResponseError("LLM provider returned a completion without choices")
            return response

        res: litellm.ModelResponse = await self._with_retry(_make, label="LLM.generate")
        return res

    async def astream(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> Any:
        """Streaming variant — returns an async iterable of response chunks."""

        def _make(include_usage: bool = True) -> Any:
            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_output_tokens,
                "stream": True,
                **self.params,
            }
            if tools:
                kwargs["tools"] = tools
            if include_usage:
                kwargs["stream_options"] = {"include_usage": True}
            return litellm.acompletion(**kwargs)

        try:
            return await self._with_retry(lambda: _make(include_usage=True), label="LLM.astream")
        except (litellm.BadRequestError, litellm.UnsupportedParamsError):
            return await self._with_retry(lambda: _make(include_usage=False), label="LLM.astream")
