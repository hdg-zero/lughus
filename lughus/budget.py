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
    bytes: int = 100_000_000
    estimated_cost: float = 100.0
    delegation_depth: int = 4

    def __post_init__(self) -> None:
        if any(getattr(self, item.name) < 0 for item in fields(self)):
            raise ValueError("Budget limits cannot be negative")


@dataclass(frozen=True, slots=True)
class BudgetAmount:
    model_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    bytes: int = 0
    estimated_cost: float = 0.0
    delegation_depth: int = 0

    def __post_init__(self) -> None:
        if any(getattr(self, item.name) < 0 for item in fields(self)):
            raise ValueError("Budget amounts cannot be negative")


class BudgetLedger:
    """Reserve before an external action, then settle actual consumption."""

    _FIELDS = ("model_calls", "tool_calls", "tokens", "bytes", "estimated_cost", "delegation_depth")

    def __init__(self, limit: BudgetLimit) -> None:
        self.limit = limit
        self._consumed = {field: 0 for field in self._FIELDS}
        self._reserved: dict[str, BudgetAmount] = {}
        self._lock = asyncio.Lock()

    async def reserve(self, amount: BudgetAmount) -> str:
        async with self._lock:
            totals = {
                field: self._consumed[field]
                + sum(getattr(v, field) for v in self._reserved.values())
                + getattr(amount, field)
                for field in self._FIELDS
            }
            for field, total in totals.items():
                if total > getattr(self.limit, field):
                    raise BudgetExceeded(field)
            key = uuid4().hex
            self._reserved[key] = amount
            return key

    async def settle(self, reservation_id: str, actual: BudgetAmount) -> None:
        async with self._lock:
            reserved = self._reserved.pop(reservation_id)
            for field in self._FIELDS:
                candidate = self._consumed[field] + getattr(actual, field)
                if candidate > getattr(self.limit, field):
                    self._reserved[reservation_id] = reserved
                    raise BudgetExceeded(field)
            for field in self._FIELDS:
                self._consumed[field] += getattr(actual, field)

    async def release(self, reservation_id: str) -> None:
        async with self._lock:
            self._reserved.pop(reservation_id, None)

    async def snapshot(self) -> Mapping[str, float]:
        async with self._lock:
            return dict(self._consumed)
