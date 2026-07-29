# Data Handling Policy

Lughus agents process a diverse array of information. Protecting sensitive information—whether it originates from user inputs, external APIs, or the LLM itself—is paramount. This document outlines the classification and handling policies for Lughus.

## Data Classification
Lughus categorizes data into four tiers:
1. **System Prompts:** Considered internal intellectual property. Should not be visible to end users.
2. **User Input:** Inherently sensitive. PII and session data reside here.
3. **Tool Outputs:** Highly variable. Often contains backend API responses or database rows.
4. **External Documents:** Context retrieved via RAG. Must be treated as untrusted and potentially sensitive.

## Redaction Rules
To ensure compliance, data is aggressively filtered at the observability layer.
- **Logs:** Framework logs only record operational states (e.g., "Tool execution started"). Arguments and outputs are never logged.
- **OTel Spans:** OpenTelemetry metrics and traces omit prompt contents, tool inputs, and tool outputs. Only metadata (e.g., tokens consumed, elapsed time, status codes) is emitted.
- **Error Payloads:** By default, all underlying stack traces and exceptions are scrubbed from public view and from the model's context unless explicitly marked as a `SafeToolError`.

## Content Capture
Capturing full prompt and completion payloads for debugging is supported but strictly **off by default**. Developers must explicitly opt-in to payload capture via configuration. Even when enabled, this capture should never be pushed to external, multi-tenant logging systems without additional scrubbing layers.

## Event Stream Visibility
The Lughus event stream captures execution history. Access to this stream is governed by `EventVisibility` levels:
- `INTERNAL`: Debugging data, raw tool payloads.
- `MODEL`: What the LLM sees (redacted errors).
- `PUBLIC`: Client-facing updates.
- `AUDIT`: Immutable history for compliance tracking.

Ensure that any API exposing events rigorously filters the stream based on the requester's authorized visibility level.
