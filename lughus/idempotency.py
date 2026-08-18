"""Idempotency protocol for tool execution receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol

from .errors import IdempotencyCapacityError
from .telemetry import meter

# Eviction weakens the exactly-once guarantee, so it must be observable.
# Without this counter an operator cannot know they crossed that line.
_evictions = meter.create_counter(
    "lughus.idempotency.evictions",
    description="Idempotency receipts dropped, by reason",
)


def idempotency_hash(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash for a (tool_name, arguments) pair."""
    canonical = json.dumps(
        {"tool": tool_name, "args": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class AttemptStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Unique identifier for a tool execution attempt."""

    run_id: str
    tool_name: str
    arguments_hash: str

    @classmethod
    def from_args(cls, run_id: str, tool_name: str, arguments: Mapping[str, Any]) -> IdempotencyKey:
        return cls(run_id, tool_name, idempotency_hash(tool_name, arguments))


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """Receipt proving that a tool was dispatched, completed, or failed."""

    key: IdempotencyKey
    status: AttemptStatus
    result: str | None = None
    error: str | None = None
    # W1-04 / C-05: wall clock, not time.monotonic(). A monotonic value has an
    # arbitrary, process-local origin, so it is meaningless once a receipt is
    # serialised or compared across processes -- which makes TTLs unusable for any
    # durable store derived from this one.
    created_at: float = field(default_factory=time.time)


class IdempotencyStore(Protocol):
    """Port for persisting execution receipts."""

    async def save(self, attempt: ExecutionAttempt) -> None: ...
    async def get(self, key: IdempotencyKey) -> ExecutionAttempt | None: ...
    async def expire(self, key: IdempotencyKey) -> None: ...
    async def claim(self, attempt: ExecutionAttempt) -> ExecutionAttempt | None: ...


class InMemoryIdempotencyStore:
    """Bounded in-memory receipt store for tests and single-process usage.

    Not a production store. Under sustained pressure it evicts the oldest
    *terminal* receipt to keep accepting work, which weakens the exactly-once
    guarantee: should the same call reappear after its receipt was evicted, the
    tool runs again. That trade-off (availability over exactly-once) is deliberate
    for a development store and is reported through the
    ``lughus.idempotency.evictions`` counter. A production guarantee requires a
    durable store.

    Two TTLs, because one value was serving two contradictory purposes (W1-04):

    ``pending_ttl_seconds``
        How long an in-flight attempt may stay PENDING before it is treated as
        orphaned (the process that claimed it died). Short by nature. Must exceed
        the longest ``tool_timeout``, otherwise a slow tool is declared orphaned
        while it is still running.
    ``ttl_seconds``
        How long a *terminal* receipt is retained, i.e. how long the
        no-repeat guarantee holds. Long by nature.
    """

    def __init__(
        self,
        *,
        max_entries: int = 10_000,
        ttl_seconds: float = 3600.0,
        pending_ttl_seconds: float = 300.0,
        now: Callable[[], float] = time.time,
    ) -> None:
        if max_entries <= 0 or ttl_seconds <= 0 or pending_ttl_seconds <= 0:
            raise ValueError("Store capacity and TTLs must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._pending_ttl = pending_ttl_seconds
        # A plain callable rather than a Clock abstraction: one parameter is enough
        # for testability and does not add an architecture.
        self._now = now
        # Insertion-ordered, which is what makes FIFO eviction free.
        self._store: dict[IdempotencyKey, ExecutionAttempt] = {}
        self._lock = asyncio.Lock()

    def _ttl_for(self, status: AttemptStatus) -> float:
        return self._pending_ttl if status == AttemptStatus.PENDING else self._ttl

    def _is_expired(self, attempt: ExecutionAttempt) -> bool:
        """True once the receipt has outlived the TTL applicable to its status.

        The previous implementation only ever returned True for PENDING, so
        COMPLETED, FAILED and OUTCOME_UNKNOWN receipts never expired and the store
        filled up permanently (N-02).
        """
        return (self._now() - attempt.created_at) > self._ttl_for(attempt.status)

    def _make_room(self, incoming: IdempotencyKey) -> None:
        """Ensure there is room for ``incoming``; caller must hold the lock.

        Purge expired receipts first, then evict the oldest terminal receipt.
        Raise only when every entry is a fresh PENDING, which is genuine
        back-pressure (max_entries tools in flight at once) and deserves an error.
        """
        if incoming in self._store or len(self._store) < self._max_entries:
            return

        for key in [k for k, v in self._store.items() if self._is_expired(v)]:
            del self._store[key]
            _evictions.add(1, {"reason": "expired"})

        while len(self._store) >= self._max_entries:
            oldest = min(
                (k for k, v in self._store.items() if v.status != AttemptStatus.PENDING),
                key=lambda k: self._store[k].created_at,
                default=None,
            )
            if oldest is None:
                raise IdempotencyCapacityError(
                    f"All {self._max_entries} idempotency receipts are in-flight "
                    f"(PENDING and not expired); reduce concurrency or raise max_entries"
                )
            del self._store[oldest]
            _evictions.add(1, {"reason": "capacity"})

    async def save(self, attempt: ExecutionAttempt) -> None:
        from .persistence import ConcurrentUpdateError

        async with self._lock:
            existing = self._store.get(attempt.key)
            if existing is not None and not self._is_expired(existing):
                if existing.status == AttemptStatus.COMPLETED:
                    return  # idempotent no-op
                if (
                    existing.status == AttemptStatus.PENDING
                    and attempt.status == AttemptStatus.PENDING
                ):
                    raise ConcurrentUpdateError(
                        "Concurrent pending attempt for the same idempotency key"
                    )
            self._make_room(attempt.key)
            # W2-15 / R12: the store's clock is authoritative.  Override the
            # dataclass default_factory (time.time) so that created_at always
            # comes from the same clock used for expiry comparisons.
            self._store[attempt.key] = replace(attempt, created_at=self._now())

    async def get(self, key: IdempotencyKey) -> ExecutionAttempt | None:
        async with self._lock:
            attempt = self._store.get(key)
            if attempt is not None and self._is_expired(attempt):
                del self._store[key]
                _evictions.add(1, {"reason": "expired"})
                return None
            return attempt

    async def claim(self, attempt: ExecutionAttempt) -> ExecutionAttempt | None:
        if attempt.status != AttemptStatus.PENDING:
            raise ValueError("An idempotency claim must start as PENDING")
        async with self._lock:
            existing = self._store.get(attempt.key)
            if existing is not None and not self._is_expired(existing):
                return existing
            if existing is not None:
                del self._store[attempt.key]
                _evictions.add(1, {"reason": "expired"})
            self._make_room(attempt.key)
            # W2-15 / R12: stamp from the store's own clock (see save()).
            self._store[attempt.key] = replace(attempt, created_at=self._now())
            return None

    async def expire(self, key: IdempotencyKey) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def purge_expired(self) -> int:
        """Drop every expired receipt and return how many were removed.

        Exposed because the store is otherwise only cleaned on write: a process
        that stops issuing tool calls would keep expired receipts in memory
        indefinitely.
        """
        async with self._lock:
            expired = [k for k, v in self._store.items() if self._is_expired(v)]
            for key in expired:
                del self._store[key]
                _evictions.add(1, {"reason": "expired"})
            return len(expired)

    def __len__(self) -> int:
        return len(self._store)
