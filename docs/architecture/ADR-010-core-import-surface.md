# ADR-010: The core imports without extras; `opentelemetry-api` is a base dependency

- **Status:** Accepted
- **Date:** 2026-08-17
- **Supersedes in part:** ADR-008 "Compatibility" section

## Context

`pip install lughus && python -c "import lughus"` failed. Three eager import chains
reached into optional extras:

| Chain | Requires | Extra |
|---|---|---|
| `infra/telemetry.py` module-level `opentelemetry.sdk.*` imports, pulled in by `engine/llm.py` and `loop/_execute.py` via `from .telemetry import meter` | `opentelemetry-sdk` | `otel` |
| `__init__.py` -> `.gateway` | `a2a-sdk` | `server` |
| `__init__.py` -> `.server` | `uvicorn`, `starlette`, `a2a-sdk` | `server` |

Only `pip install lughus[all]` ever worked. CI never caught it because every job
ran `uv sync --all-extras`.

ADR-008 asserted that "the telemetry module gracefully degrades. If OTel SDKs are
not present or not configured, it falls back to standard Python logging or no-op
providers." That statement was aspirational, not true: the SDK imports sat at
module level, so the fallback path was unreachable. This ADR corrects it.

## Decision

Two distinct root causes, addressed separately.

**1. Misplaced imports.** The `opentelemetry.sdk.*` imports move inside
`setup_telemetry()`, where the symbols are actually used, wrapped in a `try` that
raises `ImportError` naming the extra.

**2. A misclassified dependency.** The OpenTelemetry **API** is genuinely
cross-cutting in Lughus: `tracer` and `meter` are used in `loop/_loop.py`,
`loop/_execute.py` and `engine/llm.py`, and module-level counters are created at import
time. It moves from the `otel` extra into the base dependencies.
`opentelemetry-sdk` and the OTLP exporter stay in `otel`.

The API package is designed for exactly this: without an SDK,
`trace.get_tracer()` returns a no-op tracer and `metrics.get_meter()` a no-op
meter, at negligible cost, and its own footprint is limited to
`importlib-metadata` and `typing-extensions`.

**3. Lazy public surface.** `.gateway` and `.server` are resolved on first
attribute access through a `_LAZY_ATTRS` table, generalising the `__getattr__`
mechanism that already existed for `LLM`. Resolved values are memoised in
`globals()`. `ImportError` messages name the extra to install.

## Alternatives rejected

**A hand-rolled no-op tracer/meter shim.** Roughly 80 lines duplicating a
standard, guaranteed to drift, and -- decisively -- it would break context
propagation for users who *do* run OTel: Lughus spans would stop appearing inside
their parent traces. That is a functional regression for the users who care most
about observability.

**Making `tracer`/`meter` lazy behind a module `__getattr__`.** The counters are
created at import and used on hot paths; an indirection per metric buys nothing.

**Removing observability from the core.** A net functional loss. Observability in
an agent loop is not an accessory.

## Consequences

- `pip install lughus` yields a working package. `lughus[server]` and
  `lughus[otel]` add capability; they are no longer required for basic use.
- Base dependency count is unchanged: `orjson` left, `opentelemetry-api`
  arrived.
- Accessing an unavailable optional symbol raises `ImportError` naming the extra,
  instead of a bare `ModuleNotFoundError` about a third-party module the user has
  never heard of.
- `import lughus` no longer imports `litellm` either, since `.llm` was already
  lazy. Startup cost is measured separately.

## Enforcement

Two mechanisms, because documentation does not prevent regressions:

1. `tests/test_core_import_isolation.py` blocks the optional modules with a
   `sys.meta_path` finder in a subprocess, so the test is valid *in the
   all-extras development environment*. A test that merely imports `lughus` would
   pass in CI and let the regression through.
2. The `dist-core` CI job installs the built wheel with base dependencies only,
   asserts the extras are genuinely absent, and runs a real `agent_loop`.

`test_every_exported_name_resolves()` additionally catches an `__all__` entry
missing from `_LAZY_ATTRS` -- a defect class that is otherwise invisible until a
user hits it.
