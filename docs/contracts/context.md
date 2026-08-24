# Context and Provenance Contract

> **Contract stability:** This specification is stable. Future changes follow standard SemVer policy (ADR-001).

## Architecture

`ContextManager.select()` builds a context window with an explicit
character budget, preserving trusted system items and the newest complete
items. The agent loop additionally enforces a token budget over the full
message history via `ToolExecutionConfig.max_context_tokens`.

## Trust levels

Every `ContextItem` carries a `TrustLevel`:

| Level | Source | Model treatment |
|---|---|---|
| `SYSTEM` | Framework-generated | Always retained, highest priority |
| `USER` | Direct user input | Standard priority |
| `EXTERNAL` | Tool outputs, remote data | Untrusted — delimited in prompt |
| `TOOL` | Derived from tool execution | Untrusted |

External documents and tool results remain untrusted regardless of
their wording.

## Compaction

- Messages are grouped into atomic groups: an assistant message with tool
  calls plus all of its tool results are never split.
- When the estimated history exceeds `max_context_tokens`, the oldest
  non-prefix groups are **pruned** (dropped), never silently summarized.
  The prefix — system prompt, context items, user objective — is never pruned.
- Oversized individual tool outputs are handled at execution time: with
  `artifact_projection` enabled they are stored whole in artifact storage
  and the model receives a summary plus a `fetch_artifact` reference;
  otherwise they are structurally truncated.

## Non-guarantees

- `ContextManager.select()` uses a deterministic character budget, not
  exact token counts.
- History pruning uses conservative token estimates (overcounting rather
  than undercounting); production adapters should use provider-specific
  token counters for precise window management.
- Pruned content remains in the run's audit trail when events are captured
  by a durable event store; it is only removed from the model context.
