import pytest

from lughus.core.domain import RunStatus
from lughus.persistence import ConcurrentUpdateError, InMemoryRunStore
from lughus.persistence.coordinator import RunCoordinator


@pytest.mark.asyncio
async def test_transition_commits_run_event_and_checkpoint_atomically():
    store = InMemoryRunStore()
    coordinator = RunCoordinator(store)
    run = await coordinator.start("objective", tenant_id="tenant", principal_id="alice")
    running = await coordinator.transition(run, RunStatus.RUNNING, "run.started")
    assert running.version == 1
    assert (await store.read(run.run_id))[-1].type == "run.started"
    assert (await store.latest(run.run_id)).sequence == 1


@pytest.mark.asyncio
async def test_stale_transition_cannot_append_event():
    store = InMemoryRunStore()
    coordinator = RunCoordinator(store)
    run = await coordinator.start("objective", tenant_id="tenant", principal_id="alice")
    await coordinator.transition(run, RunStatus.RUNNING, "run.started")
    with pytest.raises(ConcurrentUpdateError):
        await coordinator.transition(run, RunStatus.RUNNING, "duplicate")
    assert len(await store.read(run.run_id)) == 2


@pytest.mark.asyncio
async def test_fresh_coordinator_resumes_run_monotonically():
    store = InMemoryRunStore()
    coordinator1 = RunCoordinator(store)
    run = await coordinator1.start("objective", tenant_id="tenant", principal_id="alice")
    running = await coordinator1.transition(run, RunStatus.RUNNING, "run.started")
    waiting = await coordinator1.transition(running, RunStatus.WAITING, "run.waiting")
    assert waiting.version == 2

    # A new coordinator instance simulates a worker restart or multi-process resumption
    coordinator2 = RunCoordinator(store)
    resumed = await coordinator2.transition(waiting, RunStatus.RUNNING, "run.resumed")
    assert resumed.version == 3
    events = await store.read(run.run_id)
    assert [e.type for e in events] == ["run.created", "run.started", "run.waiting", "run.resumed"]
    assert [e.sequence for e in events] == [0, 1, 2, 3]

    # Completing the run evicts it from sequences
    completed = await coordinator2.transition(resumed, RunStatus.COMPLETED, "run.completed")
    assert completed.status == RunStatus.COMPLETED
    assert run.run_id not in coordinator2._sequences
