"""Deterministic authorization decisions for tool proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class DecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ToolProposal:
    run_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    effects: frozenset[str] = field(default_factory=frozenset)
    risk: str = "unknown"
    required_scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: DecisionKind
    code: str
    reason: str = ""


class ToolPolicy(Protocol):
    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision: ...


class LeastPrivilegePolicy:
    """Default policy: deny missing scopes; approve high-risk writes."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        missing = proposal.required_scopes - principal.scopes
        if missing:
            return PolicyDecision(DecisionKind.DENY, "missing_scope", ",".join(sorted(missing)))
        if proposal.risk in {"high", "critical"} or "irreversible" in proposal.effects:
            return PolicyDecision(DecisionKind.REQUIRE_APPROVAL, "approval_required")
        return PolicyDecision(DecisionKind.ALLOW, "allowed")


class CompositePolicy:
    """Compose policies with deny taking precedence over approval and allow."""

    def __init__(self, policies: Sequence[ToolPolicy]) -> None:
        if not policies:
            raise ValueError("At least one policy is required")
        self._policies = tuple(policies)

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        decisions = [await policy.evaluate(proposal, principal) for policy in self._policies]
        for kind in (DecisionKind.DENY, DecisionKind.REQUIRE_APPROVAL):
            for decision in decisions:
                if decision.kind == kind:
                    return decision
        return decisions[-1]
