import pytest

from lughus.governance.approval import (
    ApprovalRequest,
    ApprovalStatus,
    InMemoryApprovalStore,
    proposal_digest,
)
from lughus.governance.policy import (
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


@pytest.mark.asyncio
async def test_approval_store_get_and_duplicate_create():
    store = InMemoryApprovalStore()
    assert await store.get("non_existent") is None

    args = {"param": "value"}
    request = ApprovalRequest("run_1", "my_tool", proposal_digest("my_tool", args), "low")
    await store.create(request)

    retrieved = await store.get(request.request_id)
    assert retrieved == request

    with pytest.raises(ValueError, match="already exists"):
        await store.create(request)


@pytest.mark.asyncio
async def test_approval_store_decide_edge_cases():
    store = InMemoryApprovalStore()
    with pytest.raises(KeyError):
        await store.decide("missing_id", ApprovalStatus.APPROVED, "admin")

    request = ApprovalRequest("run_1", "tool_x", proposal_digest("tool_x", {}), "high")
    await store.create(request)

    with pytest.raises(ValueError, match="must approve or reject"):
        await store.decide(request.request_id, ApprovalStatus.PENDING, "admin")


@pytest.mark.asyncio
async def test_least_privilege_policy_allow_and_irreversible_effect():
    policy = LeastPrivilegePolicy()
    principal = Principal("bob", "tenant_b", frozenset({"read", "execute"}))

    # Allowed when scopes match and risk is standard
    allowed = await policy.evaluate(
        ToolProposal("run_2", "read_file", {}, required_scopes=frozenset({"read"}), risk="low"),
        principal,
    )
    assert allowed.kind == DecisionKind.ALLOW
    assert allowed.code == "allowed"

    # Require approval when effect is irreversible even if risk is low
    irreversible = await policy.evaluate(
        ToolProposal(
            "run_3",
            "format_disk",
            {},
            effects=frozenset({"irreversible"}),
            required_scopes=frozenset({"execute"}),
            risk="low",
        ),
        principal,
    )
    assert irreversible.kind == DecisionKind.REQUIRE_APPROVAL


class _RequireApproval:
    async def evaluate(self, proposal, principal):
        return PolicyDecision(DecisionKind.REQUIRE_APPROVAL, "needs_approval")


@pytest.mark.asyncio
async def test_composite_policy_validation_and_approval_precedence():
    with pytest.raises(ValueError, match="At least one policy is required"):
        CompositePolicy([])

    decision = await CompositePolicy([_Allow(), _RequireApproval()]).evaluate(
        ToolProposal("run", "tool", {}), Principal("a", "t")
    )
    assert decision.kind == DecisionKind.REQUIRE_APPROVAL
