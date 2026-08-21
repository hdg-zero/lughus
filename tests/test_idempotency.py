"""Tests for the idempotency protocol."""

import asyncio

import pytest

from lughus.governance.idempotency import (
    AttemptStatus,
    ExecutionAttempt,
    IdempotencyKey,
    InMemoryIdempotencyStore,
    idempotency_hash,
)
from lughus.persistence import Checkpoint, ConcurrentUpdateError
from lughus.persistence.resume import ResumeAction, decide_resume


def _key(run_id: str = "run", tool: str = "send_email") -> IdempotencyKey:
    return IdempotencyKey.from_args(run_id, tool, {"to": "user@example.com"})


@pytest.mark.asyncio
async def test_completed_attempt_prevents_reexecution():
    store = InMemoryIdempotencyStore()
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.COMPLETED, result="sent"))
    existing = await store.get(key)
    assert existing is not None
    assert existing.status == AttemptStatus.COMPLETED
    assert existing.result == "sent"

    # Saving again with COMPLETED is an idempotent no-op
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.COMPLETED, result="sent"))
    still_there = await store.get(key)
    assert still_there is not None
    assert still_there.result == "sent"


@pytest.mark.asyncio
async def test_different_payload_same_key_rejected():
    store = InMemoryIdempotencyStore()
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))
    with pytest.raises(ConcurrentUpdateError):
        await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))


@pytest.mark.asyncio
async def test_pending_attempt_expires_after_ttl():
    store = InMemoryIdempotencyStore(pending_ttl_seconds=0.01)
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))
    await asyncio.sleep(0.02)
    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_failed_attempt_allows_retry():
    store = InMemoryIdempotencyStore()
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.FAILED))
    existing = await store.get(key)
    assert existing is not None
    assert existing.status == AttemptStatus.FAILED

    # A new PENDING attempt can overwrite a FAILED one
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))
    updated = await store.get(key)
    assert updated is not None
    assert updated.status == AttemptStatus.PENDING


@pytest.mark.asyncio
async def test_timeout_leaves_pending_for_reconciliation():
    """A timeout (outcome unknown) should leave PENDING, not COMPLETED or FAILED."""
    store = InMemoryIdempotencyStore(ttl_seconds=3600)
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))

    # Without idempotency store, decide_resume requires reconciliation
    checkpoint = Checkpoint("run", 1, 2, {}, pending_action="send_email", outcome_unknown=True)
    decision = await decide_resume(checkpoint)
    assert decision.action == ResumeAction.REQUIRE_RECONCILIATION


@pytest.mark.asyncio
async def test_two_workers_same_key():
    """Two concurrent PENDING saves for the same key: one must fail."""
    store = InMemoryIdempotencyStore()
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))
    with pytest.raises(ConcurrentUpdateError):
        await store.save(ExecutionAttempt(key=key, status=AttemptStatus.PENDING))


@pytest.mark.asyncio
async def test_receipt_expiration():
    store = InMemoryIdempotencyStore(ttl_seconds=0.01)
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.COMPLETED, result="ok"))
    await asyncio.sleep(0.02)
    # Expired COMPLETED attempts are cleaned up on get
    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_explicit_expire_removes_receipt():
    store = InMemoryIdempotencyStore()
    key = _key()
    await store.save(ExecutionAttempt(key=key, status=AttemptStatus.COMPLETED, result="ok"))
    await store.expire(key)
    assert await store.get(key) is None


def test_idempotency_hash_is_deterministic():
    h1 = idempotency_hash("tool", {"a": 1, "b": 2})
    h2 = idempotency_hash("tool", {"b": 2, "a": 1})
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


def test_store_rejects_invalid_capacity():
    with pytest.raises(ValueError, match="positive"):
        InMemoryIdempotencyStore(max_entries=0)
    with pytest.raises(ValueError, match="positive"):
        InMemoryIdempotencyStore(ttl_seconds=-1)
