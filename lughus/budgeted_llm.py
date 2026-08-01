"""Provider-neutral budget accounting wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .budget import BudgetAmount, BudgetLedger


def _usage(value: Any) -> BudgetAmount:
    usage = getattr(value, "usage", None)
    if usage is None:
        return BudgetAmount(model_calls=1)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    return BudgetAmount(model_calls=1, tokens=prompt + completion)


class BudgetedLLM:
    def __init__(self, inner: Any, ledger: BudgetLedger) -> None:
        self.inner, self.ledger = inner, ledger
        self.model = inner.model
        self.timeout = getattr(inner, "timeout", None)

    async def generate(self, *, messages: list[dict], tools: list[dict] | None = None) -> Any:
        reservation = await self.ledger.reserve(BudgetAmount(model_calls=1))
        try:
            response = await self.inner.generate(messages=messages, tools=tools)
            await self.ledger.settle(reservation, _usage(response))
            return response
        except BaseException:
            await self.ledger.release(reservation)
            raise

    async def astream(
        self, *, messages: list[dict], tools: list[dict] | None = None
    ) -> AsyncIterator[Any]:
        reservation = await self.ledger.reserve(BudgetAmount(model_calls=1))
        actual = BudgetAmount(model_calls=1)
        try:
            async for chunk in self.inner.astream(messages=messages, tools=tools):
                usage = _usage(chunk)
                if usage.tokens:
                    actual = usage
                yield chunk
            await self.ledger.settle(reservation, actual)
        except BaseException:
            await self.ledger.release(reservation)
            raise
