# Streaming contract — Frozen at 0.10.0

> **Contract stability:** This specification is frozen as of Lughus 0.10.0.
> Future changes follow the compatibility policy in ADR-001.

## Modes

| Mode | Behavior | Retry |
|---|---|---|
| `StreamingMode.BUFFERED` | Collects all chunks internally; yields only after the full response completes | Transparent retry on transient errors (no chunk exposed yet) |
| `StreamingMode.LIVE` | Emits each `delta.content` chunk as it arrives from the provider | **No retry after the first public delta** — partial output already observed |

## Delivery guarantees

- `buffered` preserves the retry-safe behavior from 0.1.
- `live` emits each provider delta immediately.  Once the first delta is emitted,
  a later provider error is terminal and already-emitted content is not replayed.
- Tool calls execute only after their complete arguments have been assembled
  and validated, regardless of streaming mode.

## Event visibility

- Content deltas preceding a tool call are classified as
  `EventVisibility.MODEL` (provisional, not public).
- Only deltas in the final model response (no subsequent tool call) are
  classified as `EventVisibility.PUBLIC`.
- Reasoning tokens (chain-of-thought) are always `EventVisibility.INTERNAL`
  and must never be projected to public consumers.

## Failure modes

| Failure | Behavior |
|---|---|
| Provider error before first delta | Retry in both modes |
| Provider error after first delta (live) | Terminal; emit `run.failed` event |
| Tool call after partial content | Partial text reclassified as provisional |
| Consumer disconnect | Producer may continue; no backpressure guarantee |

## Non-guarantees

- No ordering guarantee across concurrent runs.
- No backpressure mechanism — slow consumers may miss coalesced progress events.
- The exact chunking boundary depends on the LLM provider.
