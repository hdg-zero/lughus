"""receipt expiry by status, graceful eviction, wall-clock timestamps.

Three interlocking defects:

* ``_is_expired`` only ever returned True for PENDING, so COMPLETED, FAILED and
  OUTCOME_UNKNOWN receipts never expired;
* consequently the store filled up and then raised
  ``RuntimeError("Idempotency store capacity reached")`` *permanently* -- every
  idempotent tool execution failed for the remaining life of the process;
* ``created_at`` used ``time.monotonic()``, whose origin is arbitrary and
  process-local, making the TTL meaningless for any durable derivative.

Every test injects a clock. No test sleeps.
"""

from __future__ import annotations

import time

import pytest

from lughus.errors import IdempotencyCapacityError
from lughus.governance.idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    InMemoryIdempotencyStore,
)


class FakeClock:
    """Minimal controllable clock. One callable, not a Clock abstraction."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def key(index: int, run_id: str = "run-1") -> IdempotencyKey:
    return IdempotencyKey(run_id=run_id, tool_name="tool", arguments_hash=f"hash-{index}")


def attempt(
    index: int,
    status: AttemptStatus = AttemptStatus.PENDING,
    created_at: float | None = None,
    run_id: str = "run-1",
) -> ExecutionAttempt:
    kwargs = {"key": key(index, run_id), "status": status}
    if created_at is not None:
        kwargs["created_at"] = created_at
    return ExecutionAttempt(**kwargs)


# ── Expiry is per status ──────────────────────────────────────────────────────


async def test_pending_expires_after_pending_ttl_only() -> None:
    clock = FakeClock()
    store = InMemoryIdempotencyStore(ttl_seconds=3600.0, pending_ttl_seconds=300.0, now=clock)

    await store.claim(attempt(1, created_at=clock.now))

    clock.advance(299)
    assert await store.get(key(1)) is not None, "must not expire before pending_ttl"

    clock.advance(2)
    assert await store.get(key(1)) is None, "must expire after pending_ttl"


async def test_terminal_receipts_expire_after_ttl() -> None:
    """Fails on 0.10.1: terminal receipts never expired at all."""
    clock = FakeClock()
    store = InMemoryIdempotencyStore(ttl_seconds=3600.0, pending_ttl_seconds=300.0, now=clock)

    for status in (
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.OUTCOME_UNKNOWN,
    ):
        index = hash(status) % 1000
        await store.save(attempt(index, status=status, created_at=clock.now))
        assert await store.get(key(index)) is not None

    clock.advance(3601)
    for status in (
        AttemptStatus.COMPLETED,
        AttemptStatus.FAILED,
        AttemptStatus.OUTCOME_UNKNOWN,
    ):
        index = hash(status) % 1000
        assert await store.get(key(index)) is None, f"{status} should have expired"


async def test_terminal_receipt_survives_longer_than_pending() -> None:
    """The whole point of splitting the TTL."""
    clock = FakeClock()
    store = InMemoryIdempotencyStore(ttl_seconds=3600.0, pending_ttl_seconds=300.0, now=clock)

    await store.claim(attempt(1, created_at=clock.now))
    await store.save(attempt(2, status=AttemptStatus.COMPLETED, created_at=clock.now))

    clock.advance(400)
    assert await store.get(key(1)) is None, "pending should be reclaimable"
    assert await store.get(key(2)) is not None, "terminal must still hold"


async def test_expired_pending_is_reclaimable() -> None:
    """An orphaned in-flight attempt must not block re-execution forever."""
    clock = FakeClock()
    store = InMemoryIdempotencyStore(pending_ttl_seconds=300.0, now=clock)

    assert await store.claim(attempt(1, created_at=clock.now)) is None
    assert await store.claim(attempt(1, created_at=clock.now)) is not None  # still in flight

    clock.advance(301)
    assert await store.claim(attempt(1, created_at=clock.now)) is None, (
        "after pending_ttl the claim must succeed again"
    )


# ── the store must not deadlock itself ──────────────────────────────────


async def test_store_keeps_accepting_work_when_full_of_terminal_receipts() -> None:
    """Regression test: the store keeps accepting work when full of terminal receipts.

    On 0.10.1 this raises RuntimeError("Idempotency store capacity reached") and
    every subsequent idempotent tool execution fails for the life of the process.
    """
    clock = FakeClock()
    store = InMemoryIdempotencyStore(max_entries=10, now=clock)

    for i in range(10):
        await store.save(attempt(i, status=AttemptStatus.COMPLETED, created_at=clock.now + i))
    assert len(store) == 10

    assert await store.claim(attempt(999, created_at=clock.now)) is None
    assert len(store) == 10, "capacity must be respected"
    assert await store.get(key(0)) is None, "the oldest terminal receipt is evicted first"
    assert await store.get(key(9)) is not None, "newer receipts are kept"


async def test_eviction_is_fifo_on_created_at() -> None:
    # The store stamps created_at from its own clock, so
    # entries are always timestamped in insertion order.  Advance the clock
    # between saves so each entry gets a distinct created_at.
    clock = FakeClock()
    store = InMemoryIdempotencyStore(max_entries=3, now=clock)

    await store.save(attempt(1, status=AttemptStatus.COMPLETED))
    clock.advance(10)
    await store.save(attempt(2, status=AttemptStatus.COMPLETED))
    clock.advance(10)
    await store.save(attempt(3, status=AttemptStatus.COMPLETED))

    clock.advance(10)
    await store.claim(attempt(4))
    assert await store.get(key(1)) is None, "oldest created_at must go first"
    assert await store.get(key(2)) is not None
    assert await store.get(key(3)) is not None


async def test_genuine_backpressure_still_raises() -> None:
    """All entries in flight and fresh: that is real back-pressure, so it must raise."""
    clock = FakeClock()
    store = InMemoryIdempotencyStore(max_entries=3, pending_ttl_seconds=300.0, now=clock)

    for i in range(3):
        await store.claim(attempt(i, created_at=clock.now))

    with pytest.raises(IdempotencyCapacityError, match="in-flight"):
        await store.claim(attempt(99, created_at=clock.now))


async def test_capacity_error_is_catchable_as_lughus_error() -> None:
    from lughus.errors import LughusError

    assert issubclass(IdempotencyCapacityError, LughusError)


# ── Clock ─────────────────────────────────────────────────────────────────────


def test_created_at_defaults_to_wall_clock() -> None:
    """Fails on 0.10.1, which used time.monotonic()."""
    receipt = ExecutionAttempt(key=key(1), status=AttemptStatus.PENDING)
    assert abs(receipt.created_at - time.time()) < 5.0, (
        "created_at must be a wall-clock timestamp so that it survives serialisation"
    )


# ── Housekeeping ──────────────────────────────────────────────────────────────


async def test_purge_expired_reports_what_it_removed() -> None:
    clock = FakeClock()
    store = InMemoryIdempotencyStore(ttl_seconds=100.0, now=clock)

    for i in range(5):
        await store.save(attempt(i, status=AttemptStatus.COMPLETED, created_at=clock.now))
    clock.advance(101)

    assert await store.purge_expired() == 5
    assert len(store) == 0
    assert await store.purge_expired() == 0


def test_ttls_must_be_positive() -> None:
    with pytest.raises(ValueError):
        InMemoryIdempotencyStore(pending_ttl_seconds=0)
    with pytest.raises(ValueError):
        InMemoryIdempotencyStore(ttl_seconds=-1)
    with pytest.raises(ValueError):
        InMemoryIdempotencyStore(max_entries=0)
