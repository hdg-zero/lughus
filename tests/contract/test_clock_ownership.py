"""W2-15: single-clock ownership contract (R12).

Rule R12 -- an injectable clock is purely decorative if timestamps come
from elsewhere.  These tests prove that advancing the injected clock
ALONE is sufficient to cause expiration, without the test providing any
explicit timestamp.  That proves the store's clock is authoritative.

Parameterised on every store that accepts ``now=``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest


class FakeClock:
    """Controllable clock injectable into stores that accept ``now=``."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Store adapters -- uniform interface over heterogeneous store APIs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ClockContractCase:
    """Describes how to exercise a store's clock contract."""

    id: str
    ttl: float
    create: Callable[..., Any]  # (clock) -> store
    insert: Callable[..., Any]  # async (store) -> opaque key
    alive: Callable[..., Any]  # async (store, key) -> bool
    marks: tuple[Any, ...] = ()


# ---- InMemoryIdempotencyStore ---------------------------------------------


def _idem_create(clock: FakeClock) -> Any:
    from lughus.idempotency import InMemoryIdempotencyStore

    return InMemoryIdempotencyStore(
        ttl_seconds=100.0,
        pending_ttl_seconds=30.0,
        now=clock,
    )


async def _idem_insert(store: Any) -> Any:
    from lughus.idempotency import AttemptStatus, ExecutionAttempt, IdempotencyKey

    k = IdempotencyKey(run_id="run-clk", tool_name="t", arguments_hash="h1")
    # Claim then complete -- no explicit created_at anywhere.
    await store.claim(ExecutionAttempt(key=k, status=AttemptStatus.PENDING))
    await store.save(
        ExecutionAttempt(key=k, status=AttemptStatus.COMPLETED, result="ok"),
    )
    return k


async def _idem_alive(store: Any, key: Any) -> bool:
    return (await store.get(key)) is not None


# ---- BoundedInMemoryTaskStore ---------------------------------------------


def _task_create(clock: FakeClock) -> Any:
    from lughus.server import BoundedInMemoryTaskStore

    return BoundedInMemoryTaskStore(ttl_seconds=100.0, now=clock)


async def _task_insert(store: Any) -> str:
    task = MagicMock(id="task-clk-1")
    await store.save(task)
    return "task-clk-1"


async def _task_alive(store: Any, task_id: str) -> bool:
    return (await store.get(task_id)) is not None


# ---------------------------------------------------------------------------
# Parametrisation
# ---------------------------------------------------------------------------

_CASES = [
    _ClockContractCase(
        id="InMemoryIdempotencyStore",
        ttl=100.0,
        create=_idem_create,
        insert=_idem_insert,
        alive=_idem_alive,
    ),
    _ClockContractCase(
        id="BoundedInMemoryTaskStore",
        ttl=100.0,
        create=_task_create,
        insert=_task_insert,
        alive=_task_alive,
        marks=(pytest.mark.extra_server,),
    ),
]


# ---------------------------------------------------------------------------
# Contract: the injected clock is the sole authority on expiration
# ---------------------------------------------------------------------------


@pytest.mark.contract
@pytest.mark.parametrize(
    "case",
    [pytest.param(c, id=c.id, marks=c.marks) for c in _CASES],
)
async def test_injected_clock_alone_controls_expiration(
    case: _ClockContractCase,
) -> None:
    """Advancing the injected clock -- with no explicit timestamp on any
    entry -- must be sufficient to expire entries.  This proves the
    store's clock is authoritative (R12).
    """
    clock = FakeClock()
    store = case.create(clock)

    key = await case.insert(store)

    # Entry must be alive just before TTL.
    clock.advance(case.ttl - 1)
    assert await case.alive(store, key), (
        f"{case.id}: entry must be alive before TTL ({case.ttl}s)"
    )

    # Entry must expire just after TTL.
    clock.advance(2)
    assert not await case.alive(store, key), (
        f"{case.id}: entry must expire after TTL ({case.ttl}s) "
        "using only the injected clock"
    )


# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore: the store stamps created_at from its clock
# ---------------------------------------------------------------------------


@pytest.mark.contract
async def test_idempotency_store_stamps_created_at_from_own_clock() -> None:
    """Verify the store overrides default_factory=time.time with its own
    clock, so that the dataclass default is never authoritative.
    """
    from lughus.idempotency import (
        AttemptStatus,
        ExecutionAttempt,
        IdempotencyKey,
        InMemoryIdempotencyStore,
    )

    clock = FakeClock(start=9_999_999.0)
    store = InMemoryIdempotencyStore(ttl_seconds=3600.0, now=clock)

    k = IdempotencyKey(run_id="run-stamp", tool_name="t", arguments_hash="h2")

    # The attempt's default_factory stamps time.time(), which differs
    # from the injected clock.  The store MUST override it.
    await store.claim(ExecutionAttempt(key=k, status=AttemptStatus.PENDING))
    stored = await store.get(k)
    assert stored is not None
    assert stored.created_at == clock.now, (
        "The store must stamp created_at from its own clock, "
        "not from the dataclass default_factory"
    )


@pytest.mark.contract
async def test_idempotency_pending_expires_via_injected_clock() -> None:
    """PENDING entries must also expire using the injected clock alone."""
    from lughus.idempotency import (
        AttemptStatus,
        ExecutionAttempt,
        IdempotencyKey,
        InMemoryIdempotencyStore,
    )

    clock = FakeClock()
    store = InMemoryIdempotencyStore(
        ttl_seconds=3600.0,
        pending_ttl_seconds=60.0,
        now=clock,
    )

    k = IdempotencyKey(run_id="run-pend", tool_name="t", arguments_hash="h3")
    await store.claim(ExecutionAttempt(key=k, status=AttemptStatus.PENDING))

    clock.advance(59)
    assert await store.get(k) is not None, "PENDING must survive before pending_ttl"

    clock.advance(2)
    assert await store.get(k) is None, (
        "PENDING must expire after pending_ttl using only the injected clock"
    )
