---
type: API Reference
title: Approval Management API
description: API reference for lughus.approval Human-in-the-Loop management module.
---

# Approval Management API

The `lughus.approval` module manages tamper-evident human-in-the-loop (HITL) approval requests when a tool execution requires human authorization.

---

## Functions

### `proposal_digest`

```python
def proposal_digest(tool_name: str, arguments: Mapping[str, Any]) -> str:
```

Computes a deterministic SHA-256 cryptographic digest of canonicalized JSON tool proposals:
`{"tool": tool_name, "arguments": arguments}`.
Any post-approval alteration to tool arguments invalidates verification.

---

## Classes & Data Structures

### `ApprovalStatus`

Enum representing request statuses:
* `PENDING = "pending"` — Awaiting decision.
* `APPROVED = "approved"` — Approved by human operator.
* `REJECTED = "rejected"` — Rejected by human operator.
* `EXPIRED = "expired"` — Request expired before a decision was rendered.

---

### `ApprovalRequest`

```python
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

    def verify(self, arguments: Mapping[str, Any]) -> bool: ...
```

Tamper-evident record of an approval request.
* `verify(arguments)`: Returns `True` if `arguments` match the original `proposal_hash`.

---

### `InMemoryApprovalStore`

```python
class InMemoryApprovalStore:
    async def create(self, request: ApprovalRequest) -> None: ...
    async def get(self, request_id: str) -> ApprovalRequest | None: ...
    async def decide(
        self, request_id: str, status: ApprovalStatus, subject: str
    ) -> ApprovalRequest: ...
```

In-memory implementation of `ApprovalStore` protocol.
* `decide`: Atomically transitions a `PENDING` approval to `APPROVED` or `REJECTED`. Raises `ValueError` if the request is already terminal.

---

## Example Usage

```python
from lughus import ApprovalStatus, InMemoryApprovalStore

store = InMemoryApprovalStore()

# Operator retrieves request and decides
request = await store.get("approval_abc123")
if request and request.verify(proposed_arguments):
    decided = await store.decide(
        request_id="approval_abc123",
        status=ApprovalStatus.APPROVED,
        subject="admin_user",
    )
```
