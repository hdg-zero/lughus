# ADR-001: Compatibility and Release Policy

Status: accepted

## Context

Lughus is an agent micro-framework for Autonomous Agent-to-Agent (A2A) workflows. Users and integrators require clear, stable, and deterministic expectations regarding API lifecycle and semantic versioning.

## Decision

Lughus strictly adheres to **Semantic Versioning 2.0 (SemVer)**:

- **Patch releases (`x.y.Z`)**: Bug fixes, security patches, performance enhancements, and internal refactorings. No breaking changes or new public interfaces.
- **Minor releases (`x.Y.0`)**: Backward-compatible additive features, new configuration settings, and extensions to contracts.
- **Major releases (`X.0.0`)**: Breaking API changes, schema removals, or architectural paradigm shifts.
- **Wire contracts** (the `RunEvent` schema) are versioned via `SCHEMA_VERSION`. Wire format additions are backward-compatible.
- **Security corrections** may reject previously accepted unsafe configurations when necessary to protect deployments.

## Core Architectural Contracts

The following core contracts define the stability foundation of the framework:

- Run event schema (`docs/contracts/events.md`)
- Streaming delivery (`docs/contracts/streaming.md`)
- Run budgets (`docs/contracts/budgets.md`)
- Context and provenance (`docs/contracts/context.md`)
- Tool execution contract (`docs/contracts/tools.md`)

## Consequences

- Predictable upgrade paths across all major, minor, and patch releases.
- Strong guarantees for production deployments and multi-agent systems.
