import asyncio
import pytest
from lughus.approval import ApprovalRequest, ApprovalStatus, InMemoryApprovalStore, proposal_digest
from lughus.idempotency import AttemptStatus, ExecutionAttempt, IdempotencyKey, InMemoryIdempotencyStore
from lughus.runtime import ExecutionRuntime, RuntimeConfig

@pytest.mark.asyncio
async def test_idempotency_claim_is_atomic():
    store = InMemoryIdempotencyStore(); key = IdempotencyKey.from_args("run", "charge", {"amount": 1})
    gate = asyncio.Event()
    async def claim():
        await gate.wait(); return await store.claim(ExecutionAttempt(key, AttemptStatus.PENDING))
    tasks = [asyncio.create_task(claim()) for _ in range(2)]; gate.set()
    results = await asyncio.gather(*tasks); assert sum(result is None for result in results) == 1

@pytest.mark.asyncio
async def test_approved_proposal_is_reusable_by_digest():
    store = InMemoryApprovalStore(); digest = proposal_digest("charge", {"amount": 1})
    request = ApprovalRequest("run", "charge", digest, "high")
    await store.create(request); await store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")
    assert (await store.find("run", digest)).status == ApprovalStatus.APPROVED

@pytest.mark.asyncio
async def test_resource_slots_serialize_same_key():
    runtime = ExecutionRuntime(RuntimeConfig(max_global_tools=2, max_sync_workers=1)); active = 0; peak = 0
    async def work():
        nonlocal active, peak
        async with runtime.resource_slot("account:A"):
            active += 1; peak = max(peak, active); await asyncio.sleep(0); active -= 1
    await asyncio.gather(work(), work()); assert peak == 1; await runtime.close()
