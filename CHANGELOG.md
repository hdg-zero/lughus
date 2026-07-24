# Changelog

All notable changes to `lughus` will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
