# Run Event Contract

> **Contract stability:** This specification is stable. Future changes follow standard SemVer policy (ADR-001).

## Schema

Every `RunEvent` carries the following fields:

| Field | Type | Description |
|---|---|---|
| `event_id` | `str` (UUID) | Unique identifier for the event |
| `run_id` | `str` | Owning run identifier |
| `sequence` | `int ≥ 0` | Monotonically increasing within a run |
| `type` | `str` | Event type (e.g. `run.started`, `text.delta`, `run.completed`) |
| `data` | `Mapping[str, Any]` | Event-specific payload |
| `step_id` | `str \| None` | Optional step grouping |
| `causation_id` | `str \| None` | Optional causal chain link |
| `visibility` | `EventVisibility` | `INTERNAL`, `MODEL`, `PUBLIC`, or `AUDIT` |
| `occurred_at` | `str` (ISO 8601 UTC) | Wall-clock timestamp |
| `schema_version` | `str` | Currently `"1.0"` |

## Invariants

- Event sequences are **strictly increasing within a run** — event sinks
  reject out-of-order or duplicate sequences.
- A global stream offset may be used for cross-run subscription but is
  independent of per-run sequence numbers.
- Terminal run states (`COMPLETED`, `FAILED`, `CANCELLED`) are immutable —
  no further state transitions are allowed.
- Public consumers must ignore unknown event types and optional fields
  (forward compatibility).

## Visibility projection

- `INTERNAL` events never cross API boundaries.
- `MODEL` events are visible to the agent loop but not to external consumers.
- `PUBLIC` events are safe for UI/client projection.
- `AUDIT` events are logged for compliance but not projected by default.

Internal/model/audit events must be projected deliberately before
crossing an API boundary.

## Event types (non-exhaustive)

| Type | Visibility | Description |
|---|---|---|
| `run.started` | PUBLIC | Run lifecycle start |
| `text.delta` | PUBLIC | Streaming text chunk |
| `run.completed` | PUBLIC | Successful termination |
| `run.failed` | PUBLIC/INTERNAL | Error termination |
| `tool.proposed` | AUDIT | Tool call proposed by model |
| `tool.executed` | AUDIT | Tool execution result |
| `context.compacted` | INTERNAL | Context window compaction |
| `budget.updated` | INTERNAL | Budget reservation/settlement |
