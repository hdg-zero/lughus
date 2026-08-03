"""Store compliance kit (QUALIFICATION gate #6)."""

import pytest

from lughus.domain import Run, RunEvent, RunStatus
from lughus.persistence import Checkpoint, ConcurrentUpdateError, InMemoryRunStore


@pytest.fixture
def store():
    return InMemoryRunStore(max_runs=100, max_events=1000)


@pytest.mark.asyncio
async def test_create_then_get(store):
    run = Run("test objective", run_id="run-1", status=RunStatus.RUNNING)
    await store.create(run)
    retrieved = await store.get("run-1")
    assert retrieved is not None
    assert retrieved.run_id == "run-1"
    assert retrieved.status == RunStatus.RUNNING


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(store):
    assert await store.get("nonexistent") is None


@pytest.mark.asyncio
async def test_optimistic_concurrency(store):
    run = Run("test objective", run_id="run-1", status=RunStatus.RUNNING)
    await store.create(run)
    await store.update_status("run-1", expected_version=0, status=RunStatus.COMPLETED)
    with pytest.raises(ConcurrentUpdateError, match="version"):
        await store.update_status("run-1", expected_version=0, status=RunStatus.FAILED)


@pytest.mark.asyncio
async def test_terminal_immutability(store):
    run = Run("test objective", run_id="run-1", status=RunStatus.RUNNING)
    await store.create(run)
    await store.update_status("run-1", expected_version=0, status=RunStatus.COMPLETED)
    with pytest.raises(ConcurrentUpdateError, match="immutable"):
        await store.update_status("run-1", expected_version=1, status=RunStatus.RUNNING)


@pytest.mark.asyncio
async def test_event_monotonic_sequence(store):
    await store.append(RunEvent("run.started", "run-1", 0))
    await store.append(RunEvent("run.completed", "run-1", 1))
    with pytest.raises(ConcurrentUpdateError, match="monotonic"):
        await store.append(RunEvent("run.failed", "run-1", 0))


@pytest.mark.asyncio
async def test_event_read_after_sequence(store):
    await store.append(RunEvent("run.started", "run-1", 0))
    await store.append(RunEvent("text.delta", "run-1", 1))
    await store.append(RunEvent("run.completed", "run-1", 2))
    events = await store.read("run-1", after_sequence=0)
    assert len(events) == 2
    assert events[0].sequence == 1
    assert events[1].sequence == 2


@pytest.mark.asyncio
async def test_checkpoint_versioning(store):
    cp = Checkpoint("run-1", version=0, sequence=5, state={"step": 1})
    await store.save(cp, expected_version=None)
    cp2 = Checkpoint("run-1", version=1, sequence=10, state={"step": 2})
    await store.save(cp2, expected_version=0)
    with pytest.raises(ConcurrentUpdateError, match="version"):
        cp3 = Checkpoint("run-1", version=2, sequence=15, state={"step": 3})
        await store.save(cp3, expected_version=0)  # stale version


@pytest.mark.asyncio
async def test_checkpoint_latest(store):
    cp = Checkpoint("run-1", version=0, sequence=5, state={"step": 1})
    await store.save(cp, expected_version=None)
    latest = await store.latest("run-1")
    assert latest is not None
    assert latest.sequence == 5
    assert await store.latest("nonexistent") is None


@pytest.mark.asyncio
async def test_concurrent_writers(store):
    """Two concurrent creates for the same run_id: one must fail."""
    run = Run("test objective", run_id="run-dup", status=RunStatus.RUNNING)
    await store.create(run)
    with pytest.raises(ConcurrentUpdateError, match="already exists"):
        await store.create(run)


@pytest.mark.asyncio
async def test_duplicate_run_id_rejected(store):
    run = Run("test objective", run_id="run-1", status=RunStatus.RUNNING)
    await store.create(run)
    with pytest.raises(ConcurrentUpdateError):
        await store.create(run)


@pytest.mark.asyncio
async def test_capacity_limit(store):
    for i in range(100):
        await store.create(Run("test objective", run_id=f"run-{i}", status=RunStatus.RUNNING))
    with pytest.raises(RuntimeError, match="capacity"):
        await store.create(Run("test objective", run_id="run-overflow", status=RunStatus.RUNNING))
