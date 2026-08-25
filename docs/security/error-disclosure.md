> [← Documentation index](../index.md)

# Error disclosure policy

Unknown exception messages and stack traces are diagnostic data. They must not be returned
to HTTP clients or inserted into model context. Public and model-visible errors use stable
codes and deliberately safe messages. Prompts, tool arguments and outputs are not captured
by telemetry by default.

---

**Related:** [ADR-007 — Error Disclosure Boundary](../architecture/ADR-007-error-disclosure.md) · [Threat Model](threat-model.md)
