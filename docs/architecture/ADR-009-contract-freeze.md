> [← Documentation index](../index.md)

# ADR-009: Contract Stability Policy

Status: accepted  
Date: 2026-08-03

## Context

Lughus provides core public-facing contracts that define the behavior observable by integrators: event schemas, streaming modes, budget accounting, context selection, and tool execution metadata. Integrators require strict stability guarantees for production workloads.

## Decision

The core contracts are **stable**. Their schemas, field names, enum values, and behavioral invariants are governed by semantic versioning:

| Contract | Document |
|---|---|
| Run event schema | `docs/contracts/events.md` |
| Streaming delivery | `docs/contracts/streaming.md` |
| Run budgets | `docs/contracts/budgets.md` |
| Context and provenance | `docs/contracts/context.md` |
| Tool contract | `docs/contracts/tools.md` |

**Additive extensions** (new optional fields, new event types, new enum values) are permitted in minor releases, provided they do not alter the semantics of existing fields.

## Consequences

- Integrators can build against stable contracts with high confidence.
- Breaking changes require incrementing `SCHEMA_VERSION` and a major release bump per SemVer.
- Internal implementation details (internal helper functions, private classes) are decoupled from public contracts and may evolve freely.
- The `InMemoryRunStore` reference implementation is for testing and compliance verification; production deployments inject durable stores.
