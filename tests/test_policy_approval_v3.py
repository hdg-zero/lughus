import pytest

from lughus.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)
from lughus.policy import (
    CompositePolicy,
    DecisionKind,
    LeastPrivilegePolicy,
    PolicyDecision,
    Principal,
    ToolProposal,
)


@pytest.mark.asyncio
async def test_least_privilege_requires_scopes_and_approval():
    policy = LeastPrivilegePolicy()
    principal = Principal("alice", "tenant", frozenset({"read"}))
    denied = await policy.evaluate(
        ToolProposal("run", "write", {}, required_scopes=frozenset({"write"})), principal
    )
    assert denied.kind == DecisionKind.DENY
    approval = await policy.evaluate(ToolProposal("run", "delete", {}, risk="critical"), principal)
    assert approval.kind == DecisionKind.REQUIRE_APPROVAL


@pytest.mark.asyncio
async def test_approval_is_terminal_and_bound_to_arguments():
    args = {"account": "A", "amount": 10}
    request = ApprovalRequest("run", "pay", proposal_digest("pay", args), "high")
    store = InMemoryApprovalStore()
    await store.create(request)
    assert request.verify(args)
    assert not request.verify({**args, "amount": 11})
    decided = await store.decide(request.request_id, ApprovalStatus.APPROVED, "reviewer")
    assert decided.status == ApprovalStatus.APPROVED
    with pytest.raises(ValueError, match="terminal"):
        await store.decide(request.request_id, ApprovalStatus.REJECTED, "reviewer")


class _Allow:
    async def evaluate(self, proposal, principal):
        return PolicyDecision(DecisionKind.ALLOW, "ok")


class _Deny:
    async def evaluate(self, proposal, principal):
        return PolicyDecision(DecisionKind.DENY, "blocked")


@pytest.mark.asyncio
async def test_composite_policy_denial_takes_precedence():
    decision = await CompositePolicy([_Allow(), _Deny()]).evaluate(
        ToolProposal("run", "tool", {}), Principal("a", "t")
    )
    assert decision.kind == DecisionKind.DENY
