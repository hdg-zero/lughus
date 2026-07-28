"""Idempotency protocol for tool execution receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


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
    created_at: float = field(default_factory=time.monotonic)


class IdempotencyStore(Protocol):
    """Port for persisting execution receipts."""

    async def save(self, attempt: ExecutionAttempt) -> None: ...
    async def get(self, key: IdempotencyKey) -> ExecutionAttempt | None: ...
    async def expire(self, key: IdempotencyKey) -> None: ...


class InMemoryIdempotencyStore:
    """Bounded in-memory receipt store for tests and single-process usage."""

    def __init__(self, *, max_entries: int = 10_000, ttl_seconds: float = 3600.0) -> None:
        if max_entries <= 0 or ttl_seconds <= 0:
            raise ValueError("Store capacity and TTL must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._store: dict[IdempotencyKey, ExecutionAttempt] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, attempt: ExecutionAttempt) -> bool:
        return (
            attempt.status == AttemptStatus.PENDING
            and (time.monotonic() - attempt.created_at) > self._ttl
        )

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
            if len(self._store) >= self._max_entries and attempt.key not in self._store:
                self._evict_expired()
                if len(self._store) >= self._max_entries:
                    raise RuntimeError("Idempotency store capacity reached")
            self._store[attempt.key] = attempt

    async def get(self, key: IdempotencyKey) -> ExecutionAttempt | None:
        async with self._lock:
            attempt = self._store.get(key)
            if attempt is not None and self._is_expired(attempt):
                del self._store[key]
                return None
            return attempt

    async def expire(self, key: IdempotencyKey) -> None:
        async with self._lock:
            self._store.pop(key, None)

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._store.items() if self._is_expired(v)]
        for k in expired:
            del self._store[k]
