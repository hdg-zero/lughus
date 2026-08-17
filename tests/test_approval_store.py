"""W1-11: approval transitions must preserve every field, and the store is bounded.

N-13: `decide` and `consume` rebuilt ApprovalRequest by passing nine *positional*
arguments in field order. Adding, removing or reordering a field produced either a
TypeError or -- far worse -- a silent shift where `decided_by` received a
timestamp. On an object whose entire purpose is to be a tamper-evident record,
that is the wrong place for fragility.
"""

from __future__ import annotations

import dataclasses

import pytest

from lughus.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)


def make_request(index: int = 0, run_id: str = "run-1") -> ApprovalRequest:
    return ApprovalRequest(
        run_id=run_id,
        tool_name=f"tool-{index}",
        proposal_hash=proposal_digest(f"tool-{index}", {"a": index}),
        risk="high",
        expires_at="2030-01-01T00:00:00+00:00",
    )


# ── N-13: field preservation ──────────────────────────────────────────────────

# Fields each transition is allowed to change. Anything else must be carried over.
DECIDE_MUTATES = {"status", "decided_by", "decided_at"}
CONSUME_MUTATES = {"status"}


async def test_decide_preserves_every_untouched_field() -> None:
    """Stays valid when a field is added to ApprovalRequest -- that is the point."""
    store = InMemoryApprovalStore()
    original = make_request()
    await store.create(original)

    updated = await store.decide(original.request_id, ApprovalStatus.APPROVED, "alice")

    for field in dataclasses.fields(ApprovalRequest):
        if field.name in DECIDE_MUTATES:
            continue
        assert getattr(updated, field.name) == getattr(original, field.name), field.name

    assert updated.status is ApprovalStatus.APPROVED
    assert updated.decided_by == "alice"
    assert updated.decided_at is not None


async def test_consume_preserves_every_untouched_field() -> None:
    store = InMemoryApprovalStore()
    original = make_request()
    await store.create(original)
    approved = await store.decide(original.request_id, ApprovalStatus.APPROVED, "alice")

    consumed = await store.consume(original.request_id)

    for field in dataclasses.fields(ApprovalRequest):
        if field.name in CONSUME_MUTATES:
            continue
        assert getattr(consumed, field.name) == getattr(approved, field.name), field.name

    assert consumed.status is ApprovalStatus.CONSUMED
    assert consumed.decided_by == "alice", "the decider must survive consumption"


async def test_expires_at_survives_both_transitions() -> None:
    """Specifically guarded: W2-04 will start enforcing this field."""
    store = InMemoryApprovalStore()
    original = make_request()
    await store.create(original)
    await store.decide(original.request_id, ApprovalStatus.APPROVED, "alice")
    consumed = await store.consume(original.request_id)
    assert consumed.expires_at == original.expires_at


# ── Terminal statuses ─────────────────────────────────────────────────────────


async def test_deciding_twice_is_refused() -> None:
    store = InMemoryApprovalStore()
    request = make_request()
    await store.create(request)
    await store.decide(request.request_id, ApprovalStatus.APPROVED, "alice")
    with pytest.raises(ValueError, match="already terminal|not pending"):
        await store.decide(request.request_id, ApprovalStatus.REJECTED, "bob")


async def test_consuming_a_non_approved_request_is_refused() -> None:
    store = InMemoryApprovalStore()
    request = make_request()
    await store.create(request)
    with pytest.raises(ValueError):
        await store.consume(request.request_id)


# ── Bounded store ─────────────────────────────────────────────────────────────


async def test_store_evicts_terminal_requests_only() -> None:
    store = InMemoryApprovalStore(max_entries=3)

    consumed_ids = []
    for i in range(3):
        request = make_request(i)
        await store.create(request)
        await store.decide(request.request_id, ApprovalStatus.APPROVED, "alice")
        await store.consume(request.request_id)
        consumed_ids.append(request.request_id)

    fresh = make_request(99)
    await store.create(fresh)

    assert len(store) <= 3
    assert await store.get(fresh.request_id) is not None
    assert await store.get(consumed_ids[0]) is None, "oldest terminal request evicted"


async def test_store_refuses_to_evict_a_live_request() -> None:
    """Losing a pending human decision silently would be unacceptable."""
    store = InMemoryApprovalStore(max_entries=2)
    for i in range(2):
        await store.create(make_request(i))  # left PENDING

    with pytest.raises(RuntimeError, match="live"):
        await store.create(make_request(99))


def test_max_entries_must_be_positive() -> None:
    with pytest.raises(ValueError):
        InMemoryApprovalStore(max_entries=0)
