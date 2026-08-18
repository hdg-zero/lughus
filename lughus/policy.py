"""Deterministic authorization decisions for tool proposals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class DecisionKind(StrEnum):
    """Enumeration of policy evaluation decision outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated caller identity and assigned permission scopes."""

    subject: str
    tenant_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ToolProposal:
    """Proposed tool execution request evaluated against policy."""

    run_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    effects: frozenset[str] = field(default_factory=frozenset)
    risk: str = "unknown"
    required_scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Structured decision returned by a ToolPolicy evaluation."""

    kind: DecisionKind
    code: str
    reason: str = ""


class ToolPolicy(Protocol):
    """Protocol for authorization policy evaluators."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        """Evaluate a tool proposal against a principal and return a PolicyDecision."""
        ...


class AllowAllPolicy:
    """Policy that allows every proposal unconditionally."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        """Allow the proposal without further checks."""
        return PolicyDecision(DecisionKind.ALLOW, "allowed")


class LeastPrivilegePolicy:
    """Default policy: deny missing scopes; approve high-risk or irreversible writes."""

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        """Evaluate proposal against principal's scopes and tool risk level."""
        missing = proposal.required_scopes - principal.scopes
        if missing:
            return PolicyDecision(DecisionKind.DENY, "missing_scope", ",".join(sorted(missing)))
        if proposal.risk in {"high", "critical"} or "irreversible" in proposal.effects:
            return PolicyDecision(DecisionKind.REQUIRE_APPROVAL, "approval_required")
        return PolicyDecision(DecisionKind.ALLOW, "allowed")


class CompositePolicy:
    """Compose multiple policies with DENY taking precedence over REQUIRE_APPROVAL and ALLOW."""

    def __init__(self, policies: Sequence[ToolPolicy]) -> None:
        """Initialize composite policy with a non-empty sequence of policies."""
        if not policies:
            raise ValueError("At least one policy is required")
        self._policies = tuple(policies)

    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision:
        """Evaluate all composed policies and return the highest-precedence decision."""
        decisions = [await policy.evaluate(proposal, principal) for policy in self._policies]
        for kind in (DecisionKind.DENY, DecisionKind.REQUIRE_APPROVAL):
            for decision in decisions:
                if decision.kind == kind:
                    return decision
        return decisions[-1]
