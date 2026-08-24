# Changelog

All notable changes to `lughus` will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.15.0] — 2026-08-24

### Added
- **Official Visual Identity**: Introduced new official SVG vector logo (`docs/logo.svg` and `lughus/ui/logo.svg`).
- **Dynamic UI Asset Resolution**: Embedded SVG asset delivery with automatic MIME type mapping (`.svg`, `.css`, `.js`, `.html`, `.json`) in `ui_server`.
- **System Theme Synchronization**: Added live `prefers-color-scheme` OS theme listener in Developer Console with local storage persistence.

### Changed
- **Modernized Developer Console**: Replaced `test_ui` with unified `console` naming (`enable_console`, `ENABLE_CONSOLE`, `console.html/css/js`), native system typography, anti-FOUC inline theme execution, and transparent vector logo embedding.
- **Canonical Architecture Contracts**: Consolidated `docs/contracts/tools-v2.md` into `docs/contracts/tools.md`, harmonized SemVer 2.0 release policy, and purged historical freezing markers in preparation for v1.0.0.
- **Single Canonical Runner**: Promoted `GovernedAgentRunner` as the single unified agent runner with optional governance pipeline.
- **Optimized Tool JSON Pipeline**: Eliminated redundant serializations and UTF-8 encodings in tool execution path, replaced linear JSON truncation with $O(\log N)$ binary search, and unified exception normalization.
- **Token Estimation Cache**: Added bounded token caching and single-pass message pruning in message history, dramatically reducing tokenizer overhead on iterative turns.
- **Zero-Copy LLM Tool Declarations**: Eliminated recursive `copy.deepcopy` on tool declarations during LLM generation and streaming, leveraging immutable frozen schemas.

### Removed
- **Legacy Aliases**: Removed legacy `AgentRunner = GovernedAgentRunner` alias and cleaned backward compatibility shims.
- **Legacy Re-exports**: Removed `GovernedAgentRunner` re-export from `lughus.agent.application` (now cleanly imported from `lughus.agent.runner`).
- **Speculative Modules**: Removed orphaned and unconnected `lughus.persistence.resume` (`decide_resume`, `ResumeAction`, `ResumeDecision`) and `lughus.persistence.replay` (`ReplayBundle`, `RecordedCall`, `ReplayCapturePolicy`).
- **Unused Settings**: Removed unused `max_source_chars` setting from `BaseSettings`.
- **Dead UI Endpoints & Heavy Proxy**: Removed dead non-streaming `/ui/run` endpoint and eliminated the heavy server-side OpenTelemetry proxy (`/ui/otel/traces`, `_fetch_otel_url`, `_resolve_and_validate_otel_url`, `ui_otel.js`).

## [0.14.1] — 2026-08-24

### Fixed
- Fixed PyPI release workflow by granting `contents: write` permissions to the `build` job in `.github/workflows/publish.yml`, allowing `anchore/sbom-action` to attach the SBOM artifact to GitHub releases.

## [0.14.0] — 2026-08-19

### Fixed
- **P0 — BudgetedLLM.astream protocol**: rewrote `astream` from async generator to coroutine returning an internal generator, matching `StreamingLLM` protocol. Budget reservation moved inside inner generator for lazy semantics.
- **Token estimation**: `estimate_tokens` now uses `litellm.token_counter` with `len(text)//4` fallback instead of `len(text)//3`.
- **JSON-aware truncation**: tool output truncation now preserves JSON structure. Artifact projection runs before truncation so stored artifacts retain full content.
- **Dead state**: removed unused `_char_count` tracking from `MessageHistory`.
- **Config consolidation**: all `DEFAULT_*` constants centralized in `_defaults.py`; `ToolExecutionConfig` now accepts `max_global_tools` and `max_sync_thread_workers`.
- **Lazy `__version__`**: deferred `importlib.metadata.version()` to first access via `__getattr__`.
- **Subprocess env**: `test_prefix_stability` inherits full `os.environ` instead of a minimal env dict.

### Added
- **Streaming protocol contract tests** — 6 tests verifying `BudgetedLLM` wrapping of `MockStreamingLLM`.
- **Stress benchmark** — 52-turn scenario with 512-byte outputs; `large_outputs` scenario enlarged to 100KB payloads.

### Changed
- **Full package reorganization**: all modules grouped into eight layered subpackages — only `__init__.py` remains at the package root:
  - `core/` — domain, errors, events, context, artifacts, event_stream, _defaults
  - `engine/` — tools, llm, files, delegation
  - `agent/` — runner (GovernedAgentRunner), application (AgentRuntime)
  - `testing/` — mocks (MockLLM, MockStreamingLLM), evaluation
  - `governance/` — policy, approval, idempotency, budget, budgeted_llm
  - `infra/` — config, telemetry, runtime, _threading, retry
  - `persistence/` — store (was persistence.py), coordinator, replay, resume
  - `interfaces/` — server, gateway, ui_server, cli, mcp
- Top-level `from lughus import X` still works for all public symbols (lazy loading via `__getattr__`).

### Removed
- Backward-compatibility shims at old module paths (all imports must use canonical subpackage paths).
- Migration guide (`docs/guides/migration-0.10-to-0.13.md`) — framework not yet public.
- **Schema compaction (`_compact_schema`)**: parameter `description` fields are no longer stripped from tool declarations. With prefix caching, tool declarations live in the cacheable prefix and the ~376 tokens saved per call are billed at ~10% rate (~38 token-equivalents). Meanwhile, descriptions carry critical constraints (enum values, valid formats, value ranges) that the model cannot infer from parameter names alone — a single failed tool call from missing context (2000+ tokens) costs more than 50 cached calls of savings.

## [0.13.0] — 2026-08-19

### Added
- **OTel GenAI conventions** — span attributes aligned with `gen_ai.*` semantic conventions; lughus-specific attributes under `lughus.*` prefix.
- **Unified single runner** — `AgentRunner` and `GovernedAgentRunner` merged; governance is optional. `AgentRunner` is now an alias.
- **API surface snapshot** — `api_snapshot.json` tracks public API; informative test detects changes.
- **Supply chain hardening** — GitHub Actions pinned by SHA, SBOM generation, provenance attestations, dependency scanning.
- **Documentation** — README rewritten with working example; agentic design guide (A1–A8).


### Changed
- OTel attributes renamed: `gen_ai.usage.prompt_tokens` → `gen_ai.usage.input_tokens`, `gen_ai.usage.completion_tokens` → `gen_ai.usage.output_tokens`.
- Tool span attributes moved under `lughus.*` prefix.

### Removed
- **Deletion sprint** — 284 net lines removed: `StreamingMode.LIVE_AT_MOST_ONCE`, `max_message_history_chars`, dead code in gateway/delegation/ui_server, `__all__` trimmed from 100 to 89 entries.
- `AgentRunner` as a separate class (now alias for `GovernedAgentRunner`).

## [0.12.0] — 2026-08-19

### Added
- **Benchmark harness** (`benchmarks/`) with four scenarios (short, long, large_outputs, many_tools), no-network replay provider, JSON output, and baseline.
- **Incremental history** — `MessageHistory` class extends messages in place with a read-only view instead of rebuilding each turn, eliminating O(n²) allocation growth.
- **Precalculated frozen tool declarations** — `declarations()` returns memoized, frozen tuples with canonical JSON serialization; deepcopy removed.
- **Token-based context budget** — `max_context_tokens` replaces character counting; atomic groups prevent tool_call/tool_result split during pruning; `ContextBudgetExceeded` error for oversized groups.
- **Stable prefix and provider caching** — byte-identical prefix guaranteed across turns; cache hit/creation metrics forwarded to OTel counters; `prefix_reuse_pct` benchmark metric.
- **Artifact projection** (behind `artifact_projection=False` flag) — large tool outputs stored as artifacts with short reference + summary in history; `fetch_artifact` built-in tool for model retrieval.
- **TaskGroup for parallel tool execution** — `asyncio.gather` replaced with `asyncio.TaskGroup` for proper cancellation on failure.
- **Provisional and final stream chunks** — `StreamChunk` dataclass distinguishes provisional content from final `LoopResult`.
- **Tool result contract** — uniform JSON envelope (`ok`/`error`/`retryable`/`fix`), truncation declaration, anti-leak sanitization of error messages.

### Changed
- **Import time optimized** — heavy dependencies (jsonschema, opentelemetry, asyncio) lazy-loaded; `import lughus` under 100ms.
- Tool schemas always compacted (option removed).

### Removed
- `compact_tool_schemas` option from `ToolExecutionConfig` and `BaseSettings`.

## [0.11.0] — 2026-08-18

Governance contracts and integrity wave. **Breaking changes** — this is a beta
release; migration requires updating code that relied on previous defaults or
approval error handling.

### Added

- **Approval suspends run**. `ApprovalRequired`, `ApprovalRequiredGroup`,
  and `RunSuspended` exceptions derive from `LughusError` (not
  `ToolExecutionError`). The model never sees "approval_required" in tool results;
  the governed runner transitions to `WAITING` and raises `RunSuspended`.
- **Real context_items injection**. `GovernedAgentRunner.run()` now renders
  context items as `<context>` XML-tagged user messages, sorted by `(trust, id)`
  for deterministic prefix stability. Removes the `NotImplementedError` guard.
- **Honest concurrency modes**. `ConcurrencyMode` enum: `PARALLEL_SAFE`
  (new default), `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, `GLOBAL_EXCLUSIVE`.
- **Generation parameters**. `LLM(params=...)` spreads user-supplied
  parameters into provider calls, with reserved-key validation.
- **Cost in integer micros**. `estimated_cost_micros` is now `int`,
  `BudgetLedger` settles idempotently on aborted streams.
- **CI collect gate**. Differential test scanning and collection gate.
- **AllowAllPolicy**. Governed vertical slice with tool event persistence,
  sequence integrity, and checkpoint tests.
- **MCPAdapter governance bypass fix**. Schema fingerprinting prevents
  tool schema drift between refresh and invocation.
- **Governance order integration tests**. Seven tests verifying the
  eight-step governance pipeline order.
- **Single clock audit**. All timestamps use a single injectable clock.

### Changed

- **Tightened defaults**. `max_iterations` 50→12, `tool_timeout` None→30s,
  `max_tool_output_chars` 20000→8192, `max_parallel_tools` 8→4.
- **Single retry layer**. Stream-level retry removed; only LLM-level retry
  via `retry_max_elapsed=60s` remains. Mid-stream errors propagate.
- **Capacity options removed from ToolExecutionConfig**. `max_global_tools`
  and `max_sync_thread_workers` are runtime-level constants, not per-loop config.

## [0.10.2] — 2026-08-17

Correctness and packaging release. **No breaking API change**: it can be adopted
without any migration. Derived from the 0.10.1 audit and counter-audit.

### Fixed

- **`pip install lughus` produced an unusable package**. The core
  eagerly imported `opentelemetry.sdk` (via `telemetry.py`, reached from `llm.py`
  and `loop/_execute.py`), `a2a` (via `gateway.py`) and `starlette`/`uvicorn` (via
  `server.py`) — all optional extras. `opentelemetry-api` is now a base dependency
  (it is a no-op without an SDK, which is what that package is designed for), the
  SDK imports moved inside `setup_telemetry()`, and `.gateway`/`.server` resolve
  lazily. Accessing an unavailable symbol now raises `ImportError` naming the extra
  to install.
- **The idempotency store saturated permanently**. `_is_expired`
  only ever returned `True` for `PENDING`, so terminal receipts never expired; once
  10 000 had accumulated, every idempotent tool execution failed for the remaining
  life of the process. Receipts now have two TTLs (`pending_ttl_seconds` for
  orphaned in-flight attempts, `ttl_seconds` for terminal receipts), saturation
  evicts the oldest terminal receipt instead of refusing work, and
  `IdempotencyCapacityError` replaces the bare `RuntimeError`.
- **Constructing a `ToolExecutionConfig` leaked 32 threads**.
  `__post_init__` allocated an `ExecutionRuntime`, and nothing ever closed it.
  Configuration is now inert; `agent_loop`/`agent_loop_stream` own and close the
  runtime they create, and never close an injected one.
- **`max_global_tools` and `max_sync_thread_workers` had no effect**.
  The implicit runtime was built with `RuntimeConfig()` defaults. They are now
  derived from the configuration, and a conflict with an injected runtime raises
  `ValueError` instead of being ignored.
- **`ExecutionRuntime.close(wait=True)` did not wait**. `wait` was
  ignored, so `close(wait=True)` could return while synchronous tools were still
  producing side effects.
- **Resource locks accumulated without bound**. `resource_slot` never
  removed an entry, and keys derive from tool arguments — i.e. from potentially
  model-controlled data. Now reference-counted.
- **`InMemoryEventSink._last_sequence` grew forever**. The event
  buffer was bounded; the per-run sequence tracker was not.
- **`ApprovalRequest` transitions were rebuilt from nine positional arguments**.
  Adding or reordering a field would have silently shifted values on
  a tamper-evident record. Now `dataclasses.replace()`.
- **`InMemoryApprovalStore` was unbounded**. Bounded, evicting terminal
  requests only; a live pending decision is never dropped silently.
- **`context_items` was accepted and silently discarded**. It now
  raises `NotImplementedError` pending full support in 0.11.0.
  A silent lie is worse than a loud gap.
- **`registry._tools` was accessed privately by the framework itself**.
  `ToolRegistry.names()`, `__contains__` and `__len__` added.
- **Mypy targeted 3.12 while `requires-python` is `>=3.11`**, so the
  lowest supported interpreter was never type-checked.

### Added

- `ToolRegistry.names()`, `ToolRegistry.__contains__`, `ToolRegistry.__len__`.
- `IdempotencyCapacityError`, `InMemoryIdempotencyStore.purge_expired()` and
  `__len__`.
- `lughus.idempotency.evictions` counter (`reason=expired|capacity`). Eviction
  weakens the exactly-once guarantee, so it must be observable.
- Eleven strict `Fake*` dataclasses in `lughus.testing`, exported: they are the
  executable specification of the provider response shape Lughus expects.
- CI jobs `dist`, `dist-core` and `extras`: the distribution is built, installed in
  a base-dependency-only environment, imported, and functionally smoke-tested.
- `docs/architecture/ADR-010-core-import-surface.md`,
  `docs/architecture/ADR-013-runtime-ownership.md`, `docs/guides/release.md`.

### Changed

- `lughus.testing` no longer uses `MagicMock`. A `MagicMock` answers
  every attribute access, so the doubles could not fail — the root cause of a
  261-test suite missing a P0. Response shapes are now strict frozen dataclasses;
  a misspelled attribute raises `AttributeError`.
- `pytest.ini`: `filterwarnings = error` with named, dated exceptions;
  `--strict-markers`, `--strict-config`; `asyncio_default_fixture_loop_scope`
  pinned; markers declared.
- `.pre-commit-config.yaml` runs the fast test subset; the full suite with coverage
  stays in CI. A hook slow enough to be bypassed protects nothing.
- `publish.yml`: verification before publication, protected `pypi` environment,
  tag/version guard, every action pinned by SHA, and the published artefact is the
  one CI tested.

### Removed

- `orjson` from the base dependencies: it was declared and never imported.
  **Run `uv lock` before merging** — the lockfile still pins it and could
  not be regenerated offline. `uv lock --check` fails until then, deliberately.

### Deprecated

- Nothing.

### Known gaps, shipping in 0.11.0

- `BudgetedLLM` + streaming still raises `TypeError`: the `astream` contract
  fix is a breaking change and belongs in a minor release.
- `context_items` raises instead of being injected.
- Approval is still consumed before the tool dispatches, approval
  expiry is still not enforced, and a missing approval is still returned to
  the model as a tool error rather than suspending the run.


## [0.10.1] — 2026-08-03

### Fixed
- Fixed unresolved GitHub Action reference for `pypa/gh-action-pypi-publish` in `.github/workflows/publish.yml` by pointing to stable `release/v1`.

---

### Added
- Added `lughus.files` module (`lughus/files.py`) consolidating safe Base64 file decoding, file size validation, and filename sanitization (`_safe_filename`, `decode_file_bytes`, `decode_files_payload`).
- Added `shutdown_ui_server()` in `lughus.ui_server` for clean ThreadPoolExecutor teardown during Starlette/ASGI lifespan shutdown.
- Added sorted `__all__` declarations across public modules (`gateway.py`, `server.py`, `ui_server.py`, `tools.py`, `config.py`, `errors.py`, `files.py`).
- Added explicit packaging optional extras in `pyproject.toml`: `server` (FastAPI, uvicorn, Starlette, a2a-sdk), `otel` (OpenTelemetry API/SDK/exporters), and `all`.
- Added contract freeze specification document `docs/architecture/ADR-009-contract-freeze.md` freezing all core contract schemas (events, streaming, budgets, context, tools-v2) for version 0.10.0.
- Added qualification gate test suite (`tests/test_stabilization_0100.py`) certifying contract stabilization, replay security, and CI quality gates for v0.10.0.

### Changed
- Refactored `BaseGateway` (`lughus.gateway`) and `ui_server` (`lughus.ui_server`) to use the unified `lughus.files` Base64 decoding utilities.
- Connected `shutdown_ui_server()` to `ProductionGuardMiddleware` (`lughus.server`) lifespan shutdown handler.
- Made `ExecutionRuntime` strictly mandatory in `ToolExecutionConfig` and removed process-global fallback states (`_GLOBAL_TOOL_SEMAPHORES`, `_GLOBAL_TOOL_LOCK`, global `ThreadPoolExecutor`).
- Renamed `InMemoryDurableStore` to `InMemoryRunStore` in `lughus.persistence` to accurately reflect its non-durable, in-memory reference nature.
- Expanded core contract documentation (`docs/contracts/events.md`, `streaming.md`, `budgets.md`, `context.md`, `tools-v2.md`) and `docs/architecture/ADR-001-compatibility.md` with explicit freezing declarations and invariants.
- Unified HTTP 413 payload responses across `ProductionGuardMiddleware` (`lughus.server`).
- Hardened CI workflows (`.github/workflows/ci.yml`, `publish.yml`): pinned GitHub Actions by immutable SHA, enforced `--locked` lockfile resolution, and decoupled PyPI build/publish jobs.

### Fixed
- Hardened A2A error boundary in `BaseGateway.execute()` (`lughus.gateway`): unhandled internal exceptions are masked to generic error messages to prevent internal details disclosure.
- Added explicit `shutdown()` method to `BaseGateway` (`lughus.gateway`) for clean thread executor teardown.
- Added `lughus.a2a` subpackage initialisation (`lughus/a2a/__init__.py`).
- Annotated broad exception handlers in `lughus.ui_server` with `# noqa: BLE001` for strict linting compliance.

### Removed
- Removed unused private legacy aliases (`_test_ui_html`, `_decode_test_ui_files`, `_fetch_test_ui_otel_url`, `_test_ui_telemetry_event`) from `lughus.ui_server`.

---

## [0.9.0] — 2026-08-02

### Added

- Added `MCPAdapter.register_tools()` (`lughus.mcp`) routing remote MCP tools through `ToolRegistry` with conservative policy metadata (`ToolEffect.EXTERNAL`, `ToolRisk.UNKNOWN`, `requires_approval=True`).
- Added `Delegator.as_tool()` (`lughus.delegation`) exposing remote-agent delegation requests as governed tools in `ToolRegistry` (`ToolEffect.EXTERNAL`, `ToolRisk.HIGH`, `requires_approval=True`).
- Added qualification gate test suite (`tests/test_governed_integrations_090.py`).

---

## [0.8.0] — 2026-08-01

### Added

- Added `BudgetedLLM` wrapper (`lughus.budgeted_llm`) enforcing model call count and token usage reservations and settlement against `BudgetLedger`.
- Added `GovernedAgentRunner` (`lughus.application`) for governed end-to-end execution combining context window selection, budget accounting, tool policy enforcement, and transactional state transitions via `RunCoordinator`.
- Integrated `budget` accounting into `ToolExecutionConfig` and `_execute_tools` execution loop.
- Added qualification gate test suite (`tests/test_integrated_runtime_080.py`).

---

## [0.7.0] — 2026-07-31

### Added

- Added transactional `RunCoordinator` (`lughus.coordinator`) for state machine transition validation (`CREATED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`).
- Added atomic `RunUnitOfWork` context manager in `lughus.persistence` for transactional persistence across run state, checkpoint, and event stream outputs.
- Added qualification gate test suite (`tests/test_coordinator_070.py`).

---

## [0.6.0] — 2026-07-31

### Added

- Added `AgentRuntime` composition root (`lughus.application`) unifying process execution, policies, approval stores, idempotency, durability stores, telemetry events, budgets, and context managers.
- Added atomic receipt reservation and status tracking (`claim()`, `AttemptStatus.OUTCOME_UNKNOWN`) to `InMemoryIdempotencyStore` for governed tool execution.
- Added single-use approval consumption (`ApprovalStatus.CONSUMED`, `ApprovalStore.consume()`) to prevent indefinite reuse of approved proposal decisions.
- Added process-local resource slot serialization (`ExecutionRuntime.resource_slot()`) enforcing `concurrency` modes and `resource_key` scoping on tools.
- Added end-to-end Gate 0.6.0 High-Risk verification scenario (`tests/test_governed_runtime_060.py`).

### Fixed

- Fixed multi-run global stream subscriptions in `InMemoryEventSink` by tracking an incremental global event offset alongside per-run sequence numbers.

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
- Added unit test suite for durability and budget features (`tests/test_durability_budget_v4.py`).

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
