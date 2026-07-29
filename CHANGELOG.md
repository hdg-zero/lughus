# Changelog

All notable changes to `lughus` will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

---

## [0.5.1] — 2026-07-30

### Fixed

- Fixed event sequence numbers to be scoped per run ID instead of globally across runs in `InMemoryEventSink`.
- Fixed live mode propagation in `agent_loop_stream` and `AgentRunner` when `streaming_mode` is set to `StreamingMode.LIVE`.
- Fixed resume decision engine (`decide_resume`) to compute and compare cryptographic arguments hash (`pending_arguments_hash`) for idempotent resumption.
- Fixed budget ledger accounting to record observed overage in snapshots.
- Fixed delegation depth budget accounting in `Delegator` and `BudgetLedger`: delegation depth is tracked as maximum nested stack level rather than additive call count.

---

## [0.5.0] — 2026-07-29

### Added

- Added idempotency protocol for governed tool execution receipts (`lughus.idempotency`): `IdempotencyKey`, `ExecutionAttempt`, `AttemptStatus`, `IdempotencyStore`, and `InMemoryIdempotencyStore`.
- Added explicit streaming mode selection (`StreamingMode.BUFFERED`, `StreamingMode.LIVE` / `live_at_most_once`) to `agent_loop_stream()`.
- Added deterministic replay bundle serialization and integrity verification (`lughus.replay`): `ReplayBundle`, `RecordedCall`, and `REPLAY_SCHEMA_VERSION`.
- Added scenario evaluation harness for agent benchmark assertions (`lughus.evaluation`): `Scenario`, `EvaluationResult`, and `evaluate_scenario`.
- Added policy-ready Model Context Protocol client adapter (`lughus.mcp`): `MCPAdapter`, `MCPClient`, `MCPServerConfig`, and `MCPToolDescriptor`.
- Added governed remote-agent delegation primitives (`lughus.delegation`): `Delegator`, `DelegationRequest`, `DelegationResult`, `RemoteAgentClient`, and `DelegationCycleError`.
- Added architecture & integration documentation: `docs/architecture/ADR-004-run-event.md`, `docs/architecture/ADR-007-error-disclosure.md`, `docs/architecture/ADR-008-telemetry.md`, `docs/guides/evaluations.md`, `docs/integrations/mcp.md`, `docs/integrations/a2a-delegation.md`, `docs/security/data-handling.md`, `docs/operations/recovery.md`, and `docs/operations/scaling.md`.
- Added unit & compliance test suites: `tests/test_idempotency.py`, `tests/test_adversarial_scenarios.py`, `tests/test_store_compliance.py`, and `tests/test_streaming_live.py`.

---

## [0.4.0] — 2026-07-28

### Added

- Added an interactive Agent Path to the Developer Test UI, creating a clickable step for each streamed progress, tool, result, completion, and error event.
- Added a persistent light theme toggle to the Developer Test UI.
- Added the Lughus mark and refined log typography, spacing, and visual hierarchy in the Developer Test UI.
- Added collapsible tool arguments and results to the Developer Test UI, with timeline navigation opening the selected detail.
- Added frameless, responsive 100dvh full-screen Developer Test UI layout with sleek dark aesthetic and split-pane workspace.
- Added modular JavaScript frontend component architecture in `lughus/ui/`: `ui_state.js`, `ui_events.js`, `ui_history.js`, `ui_otel.js`, and `test_ui.js`.
- Added generic asset router `/ui/assets/{filename:path}` in `lughus/ui_server.py` for modular CSS/JS asset resolution.
- Added live text search input (`#event-search`) and category filtering (`All`, `Progress`, `Tools`, `Telemetry`, `Errors`) in event logs stream.
- Added auto-scroll behavior for incoming live agent event streams.
- Added optional Markdown rendering toggle for `completion` event blocks.
- Added persistence ports and reference store (`lughus.persistence`): `RunStore`, `EventStore`, `CheckpointStore`, `Checkpoint`, `InMemoryDurableStore`, and `ConcurrentUpdateError`.
- Added multi-dimensional run budget ledgers (`lughus.budget`): `BudgetLimit`, `BudgetAmount`, `BudgetLedger`, and `BudgetExceeded`.
- Added context selection and provenance management (`lughus.context`): `ContextManager`, `ContextItem`, `ContextWindow`, and `TrustLevel`.
- Added safe resume decision engine (`lughus.resume`): `decide_resume`, `ResumeAction`, and `ResumeDecision`.
- Added architecture contracts and ADR documentation: `docs/architecture/ADR-006-persistence.md`, `docs/contracts/budgets.md`, and `docs/contracts/context.md`.
- Added unit test suite for Wave 4 durability and budget features (`tests/test_durability_budget_v4.py`).

### Fixed

- Retried empty LiteLLM completion responses and now raise `LLMResponseError` instead of leaking an `IndexError` from the agent loop.
- Fixed strict grid layout containment for `.events-container` with `min-width: 0` to prevent UI overlaps.

### Changed

- Updated `CONTRIBUTING.md` commands to use `uv run` consistently and specified `--cov-branch --cov-fail-under=85` coverage gate requirements.

---

## [0.3.0] — 2026-07-25

### Added

- Added `ToolDef` v2 metadata contracts: versioning, output schemas, output validation, explicit tool effects (`ToolEffect`), risk levels (`ToolRisk`), scopes, idempotency flags, and concurrency modes (`ConcurrencyMode`).
- Added deterministic policy evaluation engine (`lughus.policy`): `Principal`, `ToolProposal`, `PolicyDecision`, `DecisionKind`, `ToolPolicy`, `LeastPrivilegePolicy`, and `CompositePolicy`.
- Added human-in-the-loop approval management (`lughus.approval`): `ApprovalRequest`, `ApprovalStatus`, `InMemoryApprovalStore`, and cryptographic argument hashing (`proposal_digest`).
- Added pre-dispatch policy evaluation and approval enforcement in core tool execution (`lughus.loop._execute`).
- Added architecture contracts and ADR documentation: `docs/architecture/ADR-005-tool-policy.md` and `docs/contracts/tools-v2.md`.
- Added API reference documentation: `docs/api/policy.md` and `docs/api/approval.md`, updated `docs/api/tools.md`, and enriched `README.md` with Governance & HITL approval section.
- Added unit test suite for policy precedence, least-privilege scoping, and tamper-evident approvals (`tests/test_policy_approval_v3.py`).

### Fixed

- Fixed `__all__` export ordering in `lughus/__init__.py` to comply with RUF022 (sorted alphabetically).
- Replaced 5 broad `except Exception` catches with targeted exception types (`socket.gaierror`, `binascii.Error`, `json.JSONDecodeError`) in `gateway.py` and `ui_server.py`.
- Added structured justification comments for 6 remaining boundary-guard `except Exception` catches required by HTTP/A2A handler security contracts.
- Added `local.properties` to `.gitignore` for AGENTS.md compliance.


---

## [0.2.0] — 2026-07-24

### Added

- Added explicit process-local `ExecutionRuntime` and `RuntimeConfig` managing worker threadpools and bulkhead semaphores.
- Added structured domain models: `Run`, `RunEvent`, `RunStatus`, `EventVisibility`, and `Usage`.
- Added pub/sub event stream sinks (`EventSink`, `InMemoryEventSink`) with monotonic sequence enforcement.
- Added `AgentRunner` orchestrator emitting `run.started`, `text.delta`, `run.completed`, and `run.failed` events.
- Added architecture contracts documentation (`docs/contracts/events.md` and `docs/contracts/streaming.md`).
- Added comprehensive unit test suite covering event sinks, runtime isolation, and runner event invariants (204 tests, 85.93% coverage).

---

## [0.1.3] — 2026-07-23

### Added

- Added `SafeToolError` exception class allowing tool authors to explicitly opt in to exposing safe business error messages and codes to the LLM.
- Added structured `error_code` and `retryable` properties to tool execution error payloads.
- Added `_NoRedirect` handler in OpenTelemetry trace fetch proxy (`ui_server.py`) to prevent SSRF redirect bypasses.
- Added `docs/security/threat-model.md` (Security boundaries and threat model) and `docs/operations-readiness.md` (Operational readiness checklist).
- Added comprehensive unit tests for `SafeToolError`, error redaction, and ASGI response guards.

### Fixed

- Fixed tool error payload leakage: unknown exceptions raised by tools are now redacted to generic `"Tool execution failed"` strings.
- Fixed ASGI protocol violation in `ProductionGuardMiddleware`: prevents duplicate 413 responses if an oversized body is detected after `http.response.start`.
- Fixed internal error disclosure in test UI server (`/ui/run`, `/ui/stream`, `/ui/otel/traces` return generic `"internal_error"` on unhandled exceptions).

---

## [0.1.2] — 2026-07-21

### Added

- Added `CORS_ALLOW_CREDENTIALS` configuration to control cross-origin credential support.
- Added strict capability check (`durable = True`) for custom `TaskStore` instances when running in production mode (`LUGHUS_ENV=production`).
- Added non-negative bounds validation (`>= 0`) for timeouts, retries, and backlog settings in `BaseSettings`.
- Added branch coverage quality gate (`fail_under = 85`) in `pyproject.toml`.
- Added Architecture Decision Records: `ADR-001` (Compatibility), `ADR-002` (Streaming), and `ADR-003` (Runtime Ownership).
- Added `docs/guarantees.md` (explicit runtime guarantees and non-guarantees) and `docs/security/error-disclosure.md` (error redaction policies).
- Added comprehensive unit tests covering settings validation, CORS constraints, TaskStore capabilities, atomic telemetry setup, and lazy imports.

### Fixed

- Fixed environment variable parsing (`_env_bool`, `_env_int`, `_env_float`) to fail fast at startup (`ValueError`) on invalid values instead of falling back silently.
- Fixed inter-field limit validation (`max_file_bytes <= max_request_bytes <= max_http_body_bytes`).
- Fixed CORS security boundary to reject wildcard origins (`CORS_ORIGINS=*`) when credentials are enabled.
- Fixed OpenTelemetry setup to ensure atomic initialization without poisoning process state on failure.

---

## [0.1.1] — 2026-07-16

### Added

- Added GitHub Actions workflow for CI (linting, type-checking, and testing matrix on Python 3.11, 3.12, 3.13).
- Added GitHub Actions workflow for CD to automate PyPI publishing using OIDC Trusted Publishing upon GitHub Releases.
- Added professional badges (PyPI version, Python support, MIT License) to `README.md`.
- Added local development git pre-commit hooks (using Ruff check and format) to ensure clean code before commits.
- Documented dev setup, testing workflow and coding style guidelines in `CONTRIBUTING.md`.

### Fixed

- Added missing metadata links (`[project.urls]`) in `pyproject.toml` to display GitHub repository links on PyPI.
- Fixed syntax parser errors in Mermaid diagrams inside `README.md`, `loop.md`, `gateway.md`, `production.md` and `testing.md` (protected special characters and reserved keywords).
- Darkened and thickened the SVG logo to ensure better contrast on both dark and light modes.

## [0.1.0] — 2026-07-15

### Added

- `agent_loop()` — agentic loop with bounded parallel tool execution.
- `agent_loop_stream()` — streaming variant yielding text chunks and a final `LoopResult`, with robust mid-stream retry handling.
- `LoopResult` — `str` subclass carrying iterations, elapsed time, token usage, and cached-token metadata.
- `ToolRegistry` — per-instance `@registry.tool()` decorator for sync and async Python tools.
- JSON Schema validation for tool schemas at registration time and for LLM arguments at execution time.
- Tool signature validation (rejection of positional-only parameters, matches with schema parameters, checks for request-scoped `state`).
- Concurrency limiting at loop iteration (`max_parallel_tools`) and worker process (`max_global_tools`) levels.
- ThreadPoolExecutor offloading for sync tools with automatic process-exit shutdown and leak-free memory management of EventLoop instances.
- Timeout guards for tool executions (`tool_timeout`, `tool_queue_timeout`) and the overall agent loop (`agent_timeout`).
- Size limits for tool arguments, tool outputs, message history, and file uploads.
- HTTP request body and backpressure guardrails (`MAX_HTTP_BODY_BYTES`, `MAX_CONCURRENT_REQUESTS`, `MAX_QUEUE_BACKLOG`).
- Timing-safe multi-key Bearer token authentication support.
- CORS configuration middleware via `CORS_ORIGINS`.
- Strict production-ready configuration checks on startup (`LUGHUS_ENV=production`).
- OpenTelemetry traces and metrics integration for monitoring loop metrics, token usage, and tool execution.
- BaseSettings dataclass loading settings dynamically from the environment and local `.env` files (with built-in `python-dotenv` support).
- Scaffolding tool (`lughus new` CLI command) with dynamic `.env.example` generation.
- Testing utilities `MockLLM` and `MockStreamingLLM`.
- Local browser developer test UI at `/ui` (packaged as `lughus.ui_server` assets) with live event streaming, Jaeger trace integration, and robust SSRF / DNS Rebinding protection.
- Shell injection hardening for A2A filename extraction in `gateway.py`.
- CI workflow configuration with pytest, coverage, mypy, and ruff.
- `py.typed` PEP 561 typing support marker.
