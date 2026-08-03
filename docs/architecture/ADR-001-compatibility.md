# ADR-001: Compatibility and release policy

Status: accepted  
Updated: 0.10.0

## Context

Lughus is a pre-1.0 micro-framework for A2A agents. As the API surface grows, users
need clear expectations about what can change and when.

## Decision

Lughus evolves additively through the 0.x series:

- **New features** are added in minor releases (0.x.0) with documentation and tests.
- **Public removals** require a documented replacement, a deprecation warning period
  of at least one minor release, contract fixtures, and a new minor release.
- **Wire events** (the `RunEvent` schema) are independently versioned via
  `SCHEMA_VERSION`. Changes to the wire format are always additive; the version
  increments only on structural changes.
- **Security corrections** may fail previously accepted unsafe configurations
  without a deprecation period.

## Frozen contracts at 0.10.0

The following contracts are frozen — their schemas, field names, and invariants
will not change until a major version:

- Run event schema v1 (`docs/contracts/events.md`)
- Streaming delivery (`docs/contracts/streaming.md`)
- Run budgets (`docs/contracts/budgets.md`)
- Context and provenance (`docs/contracts/context.md`)
- Tool contract v2 (`docs/contracts/tools-v2.md`)

See ADR-009 for the full rationale behind the contract freeze.

## Consequences

- Additive evolution allows early adopters to upgrade safely.
- The freeze at 0.10.0 provides a stable foundation for production integrations.
- Post-1.0, all breaking changes require a major version bump per semver.
