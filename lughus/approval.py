"""Tamper-evident human approval records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from .domain import new_id


class ApprovalStatus(StrEnum):
    """Lifecycle status of a human approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def proposal_digest(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Compute a canonical SHA-256 digest binding a tool proposal to its exact arguments."""
    canonical = json.dumps(
        {"tool": tool_name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Tamper-evident record requesting human approval for a tool invocation."""

    run_id: str
    tool_name: str
    proposal_hash: str
    risk: str
    request_id: str = field(default_factory=lambda: new_id("approval"))
    expires_at: str | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_by: str | None = None
    decided_at: str | None = None

    def verify(self, arguments: Mapping[str, Any]) -> bool:
        """Return True if arguments match the canonical proposal digest."""
        return self.proposal_hash == proposal_digest(self.tool_name, arguments)


class ApprovalStore(Protocol):
    """Protocol for human approval request storage and state transitions."""

    async def create(self, request: ApprovalRequest) -> None:
        """Create a new approval request in the store."""
        ...

    async def get(self, request_id: str) -> ApprovalRequest | None:
        """Fetch an approval request by ID, returning None if not found."""
        ...

    async def decide(
        self, request_id: str, status: ApprovalStatus, subject: str
    ) -> ApprovalRequest:
        """Record an approval or rejection decision for a pending request."""
        ...

    async def find(self, run_id: str, proposal_hash: str) -> ApprovalRequest | None: ...


class InMemoryApprovalStore:
    """In-memory reference implementation of ApprovalStore."""

    def __init__(self) -> None:
        """Initialize empty in-memory approval store."""
        self._items: dict[str, ApprovalRequest] = {}

    async def create(self, request: ApprovalRequest) -> None:
        """Create an approval request in memory, raising ValueError if request_id exists."""
        if request.request_id in self._items:
            raise ValueError("Approval request already exists")
        self._items[request.request_id] = request

    async def get(self, request_id: str) -> ApprovalRequest | None:
        """Retrieve an approval request from memory by request_id."""
        return self._items.get(request_id)

    async def find(self, run_id: str, proposal_hash: str) -> ApprovalRequest | None:
        matches = [
            item for item in self._items.values()
            if item.run_id == run_id and item.proposal_hash == proposal_hash
        ]
        return matches[-1] if matches else None

    async def decide(
        self, request_id: str, status: ApprovalStatus, subject: str
    ) -> ApprovalRequest:
        """Transition a pending approval request to APPROVED or REJECTED state."""
        current = self._items[request_id]
        if current.status != ApprovalStatus.PENDING:
            raise ValueError("Approval request is already terminal")
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("Decision must approve or reject")
        updated = ApprovalRequest(
            current.run_id,
            current.tool_name,
            current.proposal_hash,
            current.risk,
            current.request_id,
            current.expires_at,
            status,
            subject,
            datetime.now(UTC).isoformat(),
        )
        self._items[request_id] = updated
        return updated
