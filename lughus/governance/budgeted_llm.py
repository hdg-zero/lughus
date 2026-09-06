"""Provider-neutral budget accounting wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from ..core.domain import _extract_usage
from .budget import BudgetAmount, BudgetLedger

if TYPE_CHECKING:
    import litellm


def _usage(value: Any) -> BudgetAmount:
    usage = getattr(value, "usage", None)
    if usage is None:
        return BudgetAmount(model_calls=1)
    prompt, completion, _cached = _extract_usage(usage)
    return BudgetAmount(model_calls=1, tokens=prompt + completion)


class BudgetedLLM:
    def __init__(self, inner: Any, ledger: BudgetLedger) -> None:
        self.inner, self.ledger = inner, ledger
        self.model = inner.model
        self.timeout = getattr(inner, "timeout", None)
        self.retry_max_elapsed = getattr(inner, "retry_max_elapsed", None)

    async def generate(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> litellm.ModelResponse:
        reservation = await self.ledger.reserve(BudgetAmount(model_calls=1))
        try:
            response: litellm.ModelResponse = await self.inner.generate(
                messages=messages, tools=tools
            )
            await self.ledger.settle(reservation, _usage(response))
            return response
        except BaseException:
            await self.ledger.release(reservation)
            raise

    async def astream(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | list[dict],
        tools: Sequence[Mapping[str, Any]] | list[dict] | None = None,
    ) -> AsyncIterator[Any]:
        async def _inner() -> AsyncIterator[Any]:
            reservation = await self.ledger.reserve(BudgetAmount(model_calls=1))
            actual = BudgetAmount(model_calls=1)
            try:
                inner_stream = await self.inner.astream(messages=messages, tools=tools)
                async with aclosing(inner_stream):
                    async for chunk in inner_stream:
                        usage = _usage(chunk)
                        if usage.tokens:
                            actual = usage
                        yield chunk
            finally:
                # One attempted model request is charged on every exit path.
                # Provider usage, when available, is cumulative, not per delta.
                await self.ledger.settle(reservation, actual)

        return _inner()
