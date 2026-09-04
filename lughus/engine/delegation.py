"""Governed remote-agent delegation primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..governance.budget import BudgetAmount, BudgetLedger


class DelegationCycleError(RuntimeError):
    """Raised when recursive or cyclic remote-agent delegation is detected."""


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """Outbound delegation request to a remote agent."""

    parent_run_id: str
    target_agent: str
    skill: str
    objective: str
    causal_chain: tuple[str, ...] = ()
    permitted_data: Mapping[str, Any] = field(default_factory=dict)
    max_depth: int = 4

    def __post_init__(self) -> None:
        if self.max_depth <= 0:
            raise ValueError("max_depth must be positive")
        if self.target_agent in self.causal_chain:
            raise DelegationCycleError("Delegation cycle detected")
        if len(self.causal_chain) >= self.max_depth:
            raise DelegationCycleError("Delegation depth exceeded")


@dataclass(frozen=True, slots=True)
class DelegationResult:
    """Outcome of a completed or failed remote delegation."""

    remote_task_id: str
    status: str
    artifacts: tuple[Mapping[str, Any], ...] = ()


class RemoteAgentClient(Protocol):
    """Transport protocol for communicating with remote A2A agents."""

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        """Send a delegation request to a remote agent and await the result."""
        ...


class Delegator:
    """Governed delegation orchestrator managing budget reservations and cycle safety."""

    def __init__(self, client: RemoteAgentClient, budget: BudgetLedger) -> None:
        self.client, self.budget = client, budget

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        """Execute a delegation request under budget reservation.

        Raises:
            DelegationCycleError: If the call depth exceeds the configured budget limit.
        """
        depth = len(request.causal_chain)
        if depth > self.budget.limit.delegation_depth:
            raise DelegationCycleError("Delegation depth exceeds the runtime budget")
        reservation = await self.budget.reserve(BudgetAmount())
        try:
            result = await self.client.delegate(request)
            await self.budget.settle(reservation, BudgetAmount(delegation_depth=depth))
            return result
        except BaseException:
            await self.budget.release(reservation)
            raise
