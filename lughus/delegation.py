"""Governed remote-agent delegation primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .budget import BudgetAmount, BudgetLedger


class DelegationCycleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DelegationRequest:
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
    remote_task_id: str
    status: str
    artifacts: tuple[Mapping[str, Any], ...] = ()


class RemoteAgentClient(Protocol):
    async def delegate(self, request: DelegationRequest) -> DelegationResult: ...


class Delegator:
    def __init__(self, client: RemoteAgentClient, budget: BudgetLedger) -> None:
        self.client, self.budget = client, budget

    async def delegate(self, request: DelegationRequest) -> DelegationResult:
        reservation = await self.budget.reserve(BudgetAmount(delegation_depth=1))
        try:
            result = await self.client.delegate(request)
            await self.budget.settle(reservation, BudgetAmount(delegation_depth=1))
            return result
        except BaseException:
            await self.budget.release(reservation)
            raise
