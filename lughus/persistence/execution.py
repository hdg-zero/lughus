"""Serializable loop checkpoints and invocation-scoped durable receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.domain import canonical_hash
from ..governance.budget import BudgetAmount, BudgetLedger, BudgetLimit
from .sqlite import SQLiteStore


class OutcomeUnknown(RuntimeError):
    def __init__(self, run_id: str, call_id: str) -> None:
        super().__init__(f"Action {call_id} requires reconciliation before run {run_id} can resume")
        self.run_id, self.call_id = run_id, call_id


@dataclass
class LoopCheckpoint:
    messages: list[dict[str, Any]] = field(default_factory=list)
    prefix_len: int = 0
    iteration: int = 0
    pending_calls: list[list[str]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionJournal:
    def __init__(self, store: SQLiteStore, run_id: str, owner: str) -> None:
        self.store, self.run_id, self.owner = store, run_id, owner

    @staticmethod
    def fingerprint(name: str, version: str, args: Mapping[str, Any]) -> str:
        return canonical_hash({"tool": name, "version": version, "arguments": dict(args)})

    async def lookup(
        self, call_id: str, name: str, version: str, args: Mapping[str, Any]
    ) -> str | None:
        receipt = await self.store.action(
            self.run_id, self.owner, call_id, self.fingerprint(name, version, args)
        )
        if receipt is None:
            return None
        status, result = receipt
        if status != "completed":
            raise OutcomeUnknown(self.run_id, call_id)
        if result is None:
            raise ValueError("Completed receipt is missing its result")
        return result

    async def start(self, call_id: str, name: str, version: str, args: Mapping[str, Any]) -> None:
        await self.store.start_action(
            self.run_id, self.owner, call_id, self.fingerprint(name, version, args)
        )

    async def complete(self, call_id: str, result: str) -> None:
        await self.store.complete_action(self.run_id, self.owner, call_id, result)


class JournalBudget(BudgetLedger):
    """Per-run ledger. Persist outstanding reservations before external dispatch."""

    def __init__(
        self, limit: BudgetLimit, journal: ExecutionJournal, consumed: Mapping[str, int]
    ) -> None:
        super().__init__(limit)
        self.journal = journal
        self._consumed.update(consumed)

    async def _persist(self) -> None:
        async with self._lock:
            values = {key: self._consumed[key] + self._reserved_totals[key] for key in self._FIELDS}
            await self.journal.store.budget(self.journal.run_id, self.journal.owner, values)

    async def reserve(self, amount: BudgetAmount) -> str:
        reservation = await super().reserve(amount)
        try:
            await self._persist()
        except BaseException:
            await super().release(reservation)
            raise
        return reservation

    async def settle(self, reservation_id: str, actual: BudgetAmount) -> bool:
        result = await super().settle(reservation_id, actual)
        await self._persist()
        return result
