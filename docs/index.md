---
type: Navigation
title: Lughus Documentation
description: Index and reading order for the lughus documentation wiki.
---

# Lughus Documentation

Welcome to the lughus documentation. Every page below links back to this index (`← Index`) and suggests related pages, so you can navigate the whole wiki without leaving your editor.

**New here?** Read [Overview](overview.md) first, then follow the reading order of the *Guides* section.

## Start here

| Page | Description |
|---|---|
| [5-Minute Quickstart](quickstart.md) | Step-by-step tutorial from zero to a live agent & console |
| [Overview](overview.md) | What lughus is, architecture diagram, component map |
| [Guarantees & Non-guarantees](guarantees.md) | Explicit scope, limits and threading caveats |
| [Compatibility Policy](compatibility.md) | SemVer policy and event schema versioning |
| [Capability Maturity Matrix](maturity.md) | What is implemented / integrated / enforced |

## Guides (task-oriented)

| Page | Description |
|---|---|
| [Agentic Design](guides/agentic-design.md) | Structuring workspaces, prompts and loops |
| [Tools](guides/tools.md) | Concurrency modes, resource keys, safe tool design |
| [LLM Configuration](guides/llm.md) | Model strings, timeouts, retries |
| [Budgets](guides/budget.md) | Token/cost budgets and ledgers |
| [Testing](guides/testing.md) | MockLLM, offline tests, evaluation scenarios |
| [Evaluations](guides/evaluations.md) | Scenario-based probabilistic testing |
| [Reliability](guides/reliability.md) | Retries, idempotency, failure handling |
| [Production Guide](guides/production.md) | Deployment checklist, OpenTelemetry, hardening |
| [Release Process](guides/release.md) | How releases are cut |

## API Reference

| Page | Description |
|---|---|
| [Gateway](api/gateway.md) | `BaseGateway`, message extraction, artifacts, events |
| [Loop](api/loop.md) | `agent_loop`, `agent_loop_stream`, `ToolExecutionConfig` |
| [Tools](api/tools.md) | `ToolRegistry`, decorators, schemas, concurrency |
| [Server](api/server.md) | `build_app` / `serve`, developer console routes |
| [Runtime](api/runtime.md) | `AgentRuntime`, `RunCoordinator`, unit-of-work persistence |
| [LLM](api/llm.md) | LLM client wrapper, retry/backoff semantics |
| [Policy & Approvals](api/policy.md) | Policies, principals, decision kinds |
| [Approvals](api/approval.md) | Human-in-the-loop approval requests and stores |
| [Domain](api/domain.md) | Runs, run events, usage, visibility levels |
| [CLI](api/cli.md) | `lughus new` scaffolding |

## Contracts (stable specifications)

| Page | Description |
|---|---|
| [Events](contracts/events.md) | RunEvent schema, sequences, visibility projection |
| [Streaming](contracts/streaming.md) | BUFFERED vs LIVE modes |
| [Context](contracts/context.md) | Context window, pruning, cacheable prefixes |
| [Budgets](contracts/budgets.md) | Budget amounts, reservations, settlement |
| [Tools](contracts/tools.md) | Tool envelope contract, error payloads |

## Integrations

| Page | Description |
|---|---|
| [A2A Delegation](integrations/a2a-delegation.md) | Parent→child delegation, budgets, cycle detection, A2A exchange events |
| [MCP](integrations/mcp.md) | Model Context Protocol adapter, allowlists, limits |

## Architecture (ADRs)

Decision records — read in order if you want the "why":

1. [ADR-001 — Compatibility and Release Policy](architecture/ADR-001-compatibility.md)
2. [ADR-002 — Streaming and Retries](architecture/ADR-002-streaming.md)
3. [ADR-003 — Runtime Resource Ownership](architecture/ADR-003-runtime.md)
4. [ADR-004 — Run Event Journal](architecture/ADR-004-run-event.md)
5. [ADR-005 — Tool Capabilities and Policy Engine](architecture/ADR-005-tool-policy.md)
6. [ADR-006 — Persistence and Safe Resumption](architecture/ADR-006-persistence.md)
7. [ADR-007 — Error Disclosure Boundary](architecture/ADR-007-error-disclosure.md)
8. [ADR-008 — Telemetry](architecture/ADR-008-telemetry.md)
9. [ADR-009 — Contract Freeze](architecture/ADR-009-contract-freeze.md)
10. [ADR-010 — Core Import Surface](architecture/ADR-010-core-import-surface.md)
11. [ADR-013 — Configuration Is Inert; the Loop Owns the Execution Runtime](architecture/ADR-013-runtime-ownership.md)

## Security

| Page | Description |
|---|---|
| [Threat Model](security/threat-model.md) | Attack surfaces and mitigations |
| [Error Disclosure](security/error-disclosure.md) | Exception redaction policy |
| [Data Handling](security/data-handling.md) | Payload, artifact and telemetry data flows |

## Operations

| Page | Description |
|---|---|
| [Recovery](operations/recovery.md) | Crash recovery, checkpoints, resumption |
| [Scaling](operations/scaling.md) | Horizontal scaling, durable stores |
| [Operations Readiness](operations-readiness.md) | Production readiness checklist |
