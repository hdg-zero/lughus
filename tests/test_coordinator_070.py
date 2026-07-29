import pytest

from lughus.coordinator import RunCoordinator
from lughus.domain import RunStatus
from lughus.persistence import ConcurrentUpdateError, InMemoryDurableStore


@pytest.mark.asyncio
async def test_transition_commits_run_event_and_checkpoint_atomically():
    store = InMemoryDurableStore()
    coordinator = RunCoordinator(store)
    run = await coordinator.start("objective", tenant_id="tenant", principal_id="alice")
    running = await coordinator.transition(run, RunStatus.RUNNING, "run.started")
    assert running.version == 1
    assert (await store.read(run.run_id))[-1].type == "run.started"
    assert (await store.latest(run.run_id)).sequence == 1


@pytest.mark.asyncio
async def test_stale_transition_cannot_append_event():
    store = InMemoryDurableStore()
    coordinator = RunCoordinator(store)
    run = await coordinator.start("objective", tenant_id="tenant", principal_id="alice")
    await coordinator.transition(run, RunStatus.RUNNING, "run.started")
    with pytest.raises(ConcurrentUpdateError):
        await coordinator.transition(run, RunStatus.RUNNING, "duplicate")
    assert len(await store.read(run.run_id)) == 2
