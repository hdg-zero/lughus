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

    def register_tool(self, registry: Any, *, name: str = "delegate_agent") -> None:
        """Expose delegation through ToolRegistry so policy and approval cannot be bypassed."""
        from .tools import ConcurrencyMode, ToolEffect, ToolRisk

        @registry.tool(
            name,
            "Delegate a bounded objective to an approved remote agent",
            {
                "type": "object",
                "properties": {
                    "parent_run_id": {"type": "string"},
                    "target_agent": {"type": "string"},
                    "skill": {"type": "string"},
                    "objective": {"type": "string"},
                    "causal_chain": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["parent_run_id", "target_agent", "skill", "objective"],
                "additionalProperties": False,
            },
            effects=frozenset({ToolEffect.EXTERNAL}),
            risk=ToolRisk.HIGH,
            requires_approval=True,
            concurrency=ConcurrencyMode.PARALLEL_SAFE,
        )
        async def _delegate(
            *,
            state: dict,
            parent_run_id: str,
            target_agent: str,
            skill: str,
            objective: str,
            causal_chain: list[str] | None = None,
        ) -> dict[str, Any]:
            del state
            result = await self.delegate(
                DelegationRequest(
                    parent_run_id, target_agent, skill, objective, tuple(causal_chain or ())
                )
            )
            return {
                "remote_task_id": result.remote_task_id,
                "status": result.status,
                "artifacts": list(result.artifacts),
            }
