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
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def proposal_digest(tool_name: str, arguments: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"tool": tool_name, "arguments": arguments},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
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
        return self.proposal_hash == proposal_digest(self.tool_name, arguments)


class ApprovalStore(Protocol):
    async def create(self, request: ApprovalRequest) -> None: ...
    async def get(self, request_id: str) -> ApprovalRequest | None: ...
    async def decide(
        self, request_id: str, status: ApprovalStatus, subject: str
    ) -> ApprovalRequest: ...


class InMemoryApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}

    async def create(self, request: ApprovalRequest) -> None:
        if request.request_id in self._items:
            raise ValueError("Approval request already exists")
        self._items[request.request_id] = request

    async def get(self, request_id: str) -> ApprovalRequest | None:
        return self._items.get(request_id)

    async def decide(
        self, request_id: str, status: ApprovalStatus, subject: str
    ) -> ApprovalRequest:
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
