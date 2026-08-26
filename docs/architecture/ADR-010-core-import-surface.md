# ADR-010: Core Import Surface and Dependency Isolation

- **Status:** Accepted
- **Date:** 2026-08-17

## Context

Lughus is packaged with lightweight core dependencies and optional extras (`server`, `otel`). The core package must import cleanly and execute agent loops without requiring any optional extras installed.

## Decision

1. **Explicit SDK Isolation:** Third-party optional SDK imports (e.g. `opentelemetry.sdk.*`, `starlette`, `uvicorn`, `a2a-sdk`) are kept inside specific functions or lazy module paths and guarded with explicit informative `ImportError` messages.
2. **OpenTelemetry API as Base Dependency:** The `opentelemetry-api` package is a lightweight, standard base dependency. It provides zero-overhead no-op implementations when no SDK is registered and preserves context propagation.
3. **Lazy Public Surface:** Heavy or extra-dependent modules (`engine.llm`, `interfaces.gateway`, `interfaces.server`) are resolved lazily on first attribute access through `_LAZY_ATTRS` and `__getattr__`.

## Consequences

- `pip install lughus` yields a functional core without heavy dependencies.
- Accessing an optional symbol when its extra is missing raises a descriptive `ImportError` naming the extra to install.
- Core imports remain fast and free of unnecessary background runtime dependencies.

## Enforcement

- `tests/test_core_import_isolation.py` enforces import isolation using a `sys.meta_path` blocker in subprocesses.
- CI pipeline validates base-wheel installation and execution in an environment with zero optional extras.
