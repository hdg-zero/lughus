# ADR-009: Contract freeze at 0.10.0

Status: accepted  
Date: 2026-08-03

## Context

By version 0.10.0, Lughus has accumulated five public-facing contracts that define
the behavior observable by integrators: event schemas, streaming modes, budget
accounting, context selection, and tool metadata. Early adopters need a stability
guarantee before committing to production integrations.

## Decision

All five contracts are **frozen** at 0.10.0. Their schemas, field names, enum
values, and behavioral invariants will not change until a major version bump (1.0+):

| Contract | Document |
|---|---|
| Run event v1 | `docs/contracts/events.md` |
| Streaming delivery | `docs/contracts/streaming.md` |
| Run budgets | `docs/contracts/budgets.md` |
| Context and provenance | `docs/contracts/context.md` |
| Tool contract v2 | `docs/contracts/tools-v2.md` |

**Additive extensions** (new optional fields, new event types, new enum values)
are permitted without a version bump, provided they do not alter the semantics
of existing fields.

## Consequences

- Integrators can build against frozen schemas with confidence.
- Breaking changes require incrementing `SCHEMA_VERSION` and a new major release.
- Internal implementation details (metric names, logging formats, module layout)
  are explicitly excluded from the freeze and may evolve freely.
- The `InMemoryRunStore` reference implementation is excluded from the freeze;
  it exists for testing and may change its internal structure.
