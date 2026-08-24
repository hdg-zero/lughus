"""Atomic, multi-dimensional run budgets."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, fields
from uuid import uuid4


class BudgetExceeded(RuntimeError):
    def __init__(self, dimension: str) -> None:
        super().__init__(f"Run budget exceeded: {dimension}")
        self.dimension = dimension


@dataclass(frozen=True, slots=True)
class BudgetLimit:
    model_calls: int = 100
    tool_calls: int = 100
    tokens: int = 1_000_000
    delegation_depth: int = 4

    def __post_init__(self) -> None:
        if any(getattr(self, item.name) < 0 for item in fields(self)):
            raise ValueError("Budget limits cannot be negative")


@dataclass(frozen=True, slots=True)
class BudgetAmount:
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    delegation_depth: int = 0

    def __post_init__(self) -> None:
        if any(getattr(self, item.name) < 0 for item in fields(self)):
            raise ValueError("Budget amounts cannot be negative")


class BudgetLedger:
    """Reserve before an external action, then settle actual consumption."""

    _FIELDS = (
        "model_calls",
        "tool_calls",
        "tokens",
        "delegation_depth",
    )

    def __init__(self, limit: BudgetLimit) -> None:
        self.limit = limit
        self._consumed = {field: 0 for field in self._FIELDS}
        self._reserved: dict[str, BudgetAmount] = {}
        self._reserved_totals = {field: 0 for field in self._FIELDS}
        self._lock = asyncio.Lock()

    async def reserve(self, amount: BudgetAmount) -> str:
        async with self._lock:
            for field in self._FIELDS:
                if self._consumed[field] + self._reserved_totals[field] + getattr(
                    amount, field
                ) > getattr(self.limit, field):
                    raise BudgetExceeded(field)
            key = uuid4().hex
            self._reserved[key] = amount
            for field in self._FIELDS:
                self._reserved_totals[field] += getattr(amount, field)
            return key

    async def settle(self, reservation_id: str, actual: BudgetAmount) -> None:
        async with self._lock:
            amount = self._reserved.pop(reservation_id, None)
            if amount is not None:
                for field in self._FIELDS:
                    self._reserved_totals[field] -= getattr(amount, field)
                for field in self._FIELDS:
                    if field == "delegation_depth":
                        self._consumed[field] = max(self._consumed[field], actual.delegation_depth)
                    else:
                        self._consumed[field] += getattr(actual, field)

    async def would_exceed(self) -> tuple[str, ...]:
        async with self._lock:
            return tuple(
                field
                for field in self._FIELDS
                if self._consumed[field] > getattr(self.limit, field)
            )

    async def release(self, reservation_id: str) -> None:
        async with self._lock:
            amount = self._reserved.pop(reservation_id, None)
            if amount is not None:
                for field in self._FIELDS:
                    self._reserved_totals[field] -= getattr(amount, field)

    async def outstanding(self) -> Mapping[str, BudgetAmount]:
        """Return a snapshot of currently outstanding reservations."""
        async with self._lock:
            return dict(self._reserved)

    async def snapshot(self) -> Mapping[str, int]:
        async with self._lock:
            return dict(self._consumed)
