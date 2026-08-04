# Context and provenance — Frozen at 0.10.0

> **Contract stability:** This specification is frozen as of Lughus 0.10.0.
> Future changes follow the compatibility policy in ADR-001.

## Architecture

`ContextManager.select()` builds a context window respecting the
provider's token limit before each model call.

## Trust levels

Every `ContextItem` carries a `TrustLevel`:

| Level | Source | Model treatment |
|---|---|---|
| `SYSTEM` | Framework-generated | Always retained, highest priority |
| `VERIFIED` | Authenticated internal source | Retained when space allows |
| `USER` | Direct user input | Standard priority |
| `EXTERNAL` | Tool outputs, remote data | Untrusted — delimited in prompt |

External documents and tool results remain untrusted regardless of
their wording.

## Compaction

- Messages are grouped so that assistant/tool pairs are never split.
- When the window is full, oldest non-pinned messages are compacted
  into a summary and a `context.compacted` event is emitted.
- Large tool outputs are offloaded to artifact storage; the model
  receives a reference and a controlled summary.

## Non-guarantees

- The reference context selector uses a deterministic character budget,
  not exact token counts.
- Production adapters should use provider-specific token counters for
  precise window management.
- Summaries generated during compaction do not replace the original
  content in the audit trail.
