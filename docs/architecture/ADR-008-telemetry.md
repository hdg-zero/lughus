# ADR-008: Telemetry Ownership

## Context
Observability is critical for AI agents. Tracing LLM calls, tool execution times, and error rates is necessary for production deployment. However, framework-level OpenTelemetry (OTel) integration often conflicts with application-level configurations. We needed a strategy for integrating tracing and metrics into Lughus without hijacking the host application's observability stack.

## Decision
Lughus utilizes atomic initialization for OpenTelemetry (`lughus.infra.telemetry`) and scopes its telemetry purely to its own operations.
- **Initialization:** We use a thread-safe atomic lock (`_INIT_LOCK`) to ensure OTel providers are only instantiated once, and only if requested via Lughus's internal setup routine.
- **Conventions:** All telemetry items (spans, metrics) are prefixed with the `lughus.*` namespace.
- **Prompt Capture:** We decided **not** to capture actual prompt or completion text by default in traces. Only metadata and token usage are logged to prevent sensitive data leakage.
- **Shutdown:** Telemetry shutdown is performed cleanly with flush commands ensuring no spans are dropped when an agent process exits.

## Alternatives
- **Global Provider Ownership:** We evaluated forcibly setting the global `TracerProvider` and `MeterProvider`. This was rejected because Lughus is a micro-framework; the integrating host application should retain ultimate control over the OTel pipeline.
- **Custom Telemetry Facade:** Building a custom wrapper instead of OTel was deemed redundant since the OTel standard is ubiquitous.

## Consequences
- Integrating Lughus into an existing OTel-instrumented application requires no changes. Lughus simply retrieves named tracers (`trace.get_tracer("lughus")`).
- Lughus metrics are designed with controlled cardinality. High-cardinality values like `run_id` are explicitly excluded from metrics (like `lughus.tool.errors`) to prevent time-series database explosion.

## Compatibility
The telemetry module gracefully degrades. If OTel SDKs are not present or not configured, it falls back to standard Python logging or no-op providers.

## Security
By omitting prompt texts and tool arguments from telemetry by default, we eliminate a major vector for PII and credential leakage in centralized logging systems.
