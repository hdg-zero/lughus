> [← Documentation index](../index.md)

# ADR-007: Error Disclosure Policy

## Context
When an AI agent executes tools, errors are an inevitable part of the process. Lughus needs a consistent strategy for handling execution exceptions (`lughus.core.errors`). We must balance the model's need for actionable error messages (so the agent can retry or correct its approach) with the critical security requirement of not leaking internal system details, stack traces, or credentials to the LLM context or upstream clients.

## Decision
We implemented a strict, opt-in error disclosure policy (`lughus.loop._execute`).
- All unknown or standard exceptions raised during tool execution are redacted outright. They are converted into a generic "Tool execution failed" JSON response.
- To expose a descriptive error message to the model, developers must explicitly raise `SafeToolError`.
- `SafeToolError` requires a stable `code` and an explicit public `message`.

## Classification
Error visibility is classified across three boundaries:
1. **public_message:** Handled by HTTP clients. The `SafeToolError` explicitly maps what is visible.
2. **model_message:** What the LLM sees in its prompt history. Only `SafeToolError`, `ToolValidationError`, and `ToolTimeoutError` pass their messages to the model.
3. **diagnostic:** Full tracebacks and exception context are retained strictly in diagnostic outputs (such as OpenTelemetry spans and application logs) for developer debugging.

## Alternatives
- **Default Disclosure:** Passing all exception strings back to the LLM was rejected due to the high risk of exposing database connection strings, paths, or underlying system architectures.
- **Regex Scrubbing:** Attempting to sanitize exceptions via regular expressions is brittle and often fails against unexpected edge cases.

## Consequences
- Tool authors must be diligent about explicitly raising `SafeToolError` for expected failure modes if they want the AI to intelligently recover.
- Security audits are simplified as the framework handles redaction centrally.

Standard Python exceptions like `ValueError` or `RuntimeError` safely degrade to generic failure messages without leaking internal tracebacks.

## Security
This approach ensures zero secrets leak into error payloads. Correlation IDs are used in the diagnostic spans to link the redacted public errors back to their true root causes in the telemetry system.
