# Changelog

All notable changes to `lughus` will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
