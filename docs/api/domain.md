---
type: API Reference
title: Domain Models API
description: API reference for lughus.core.domain domain records.
---

# Domain Models API

The `lughus.core.domain` module defines immutable, versioned domain models for observable agent execution.

---

## Functions

### `new_id(prefix: str) -> str`

Generates a unique prefixed identifier string (e.g. `run_a1b2c3d4...`, `approval_e5f6g7h8...`).

---

## Enums & Data Classes

### `RunStatus`

Enum representing the lifecycle status of a run:
* `PENDING = "pending"`
* `RUNNING = "running"`
* `WAITING = "waiting"`
* `COMPLETED = "completed"`
* `FAILED = "failed"`
* `CANCELLED = "cancelled"`

Property `terminal` returns `True` for `COMPLETED`, `FAILED`, and `CANCELLED`.

---

### `EventVisibility`

Enum classifying event visibility levels:
* `INTERNAL = "internal"` — System-level execution events.
* `MODEL = "model"` — Events visible to the LLM.
* `PUBLIC = "public"` — User-facing public events.
* `AUDIT = "audit"` — Security and governance audit log events.

---

### `Usage`

```python
@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost: float = 0.0
```

Token consumption metrics and estimated execution cost record.

---

### `RunEvent`

```python
@dataclass(frozen=True, slots=True)
class RunEvent:
    type: str
    run_id: str
    sequence: int
    data: Mapping[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: new_id("evt"))
    step_id: str | None = None
    causation_id: str | None = None
    visibility: EventVisibility = EventVisibility.INTERNAL
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    schema_version: str = "1.0"
```

Structured immutable event emitted during run execution.

---

### `Run`

```python
@dataclass(frozen=True, slots=True)
class Run:
    objective: str
    run_id: str = field(default_factory=lambda: new_id("run"))
    status: RunStatus = RunStatus.PENDING
    version: int = 0
    context_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    usage: Usage = field(default_factory=Usage)
    tenant_id: str = "default"
    principal_id: str = "anonymous"
```

Top-level execution run record.
