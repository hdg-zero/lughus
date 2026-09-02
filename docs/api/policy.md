---
type: API Reference
title: Policy Engine API
description: API reference for lughus.governance.policy deterministic authorization module.
---

> [← Documentation index](../index.md)

# Policy Engine API

The `lughus.governance.policy` module provides deterministic authorization primitives evaluated prior to tool execution in the agent loop.

---

## Classes & Data Structures

### `DecisionKind`

Enum representing policy evaluation outcomes:
* `ALLOW = "allow"` — Action is authorized for execution.
* `DENY = "deny"` — Action is forbidden. Tool execution fails immediately.
* `REQUIRE_APPROVAL = "require_approval"` — Action requires explicit human approval before execution.

---

### `Principal`

```python
@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
```

Represents the caller context executing the agent loop.
* `subject`: Unique identifier of the calling user or system.
* `tenant_id`: Multi-tenant organization or environment identifier.
* `scopes`: Frozenset of granted security scopes (e.g., `frozenset(["read", "finance:transfer"])`).

---

### `ToolProposal`

```python
@dataclass(frozen=True, slots=True)
class ToolProposal:
    run_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    effects: frozenset[str] = field(default_factory=frozenset)
    risk: str = "unknown"
    required_scopes: frozenset[str] = field(default_factory=frozenset)
```

Structured payload containing all details of a requested tool execution passed to the policy engine.

---

### `PolicyDecision`

```python
@dataclass(frozen=True, slots=True)
class PolicyDecision:
    kind: DecisionKind
    code: str
    reason: str = ""
```

Result returned by a `ToolPolicy` evaluation.

---

## Policies

### `LeastPrivilegePolicy`

```python
class LeastPrivilegePolicy:
    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision: ...
```

Default built-in policy enforcing strict least-privilege principles:
1. Denies execution if `proposal.required_scopes` is not a subset of `principal.scopes`.
2. Returns `REQUIRE_APPROVAL` if tool risk is `high` or `critical`, or if `effects` contain `irreversible`.
3. Otherwise returns `ALLOW`.

---

### `CompositePolicy`

```python
class CompositePolicy:
    def __init__(self, policies: Sequence[ToolPolicy]) -> None: ...
    async def evaluate(self, proposal: ToolProposal, principal: Principal) -> PolicyDecision: ...
```

Composes multiple policies with deterministic precedence: `DENY` > `REQUIRE_APPROVAL` > `ALLOW`.

---

## Example Usage

```python
from lughus import (
    CompositePolicy,
    LeastPrivilegePolicy,
    Principal,
    ToolExecutionConfig,
    agent_loop,
)

principal = Principal(
    subject="user_123",
    tenant_id="org_abc",
    scopes=frozenset(["finance:read", "finance:transfer"]),
)

policy = CompositePolicy([LeastPrivilegePolicy()])

config = ToolExecutionConfig(
    policy=policy,
    principal=principal,
)
```

---

**Related:** [Approvals API](approval.md) · [ADR-005 — Tool Policy](../architecture/ADR-005-tool-policy.md)
