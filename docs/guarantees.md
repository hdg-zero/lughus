> [← Documentation index](index.md)

# Guarantees and Non-Guarantees

Lughus validates tool inputs and bounds configured payloads. Limits are scoped to one application runtime unless explicitly documented otherwise. The in-memory task store is not durable and is not suitable for multiple replicas.

Streaming supports two explicit modes (`StreamingMode`):
- `BUFFERED`: Retry-safe execution where text is emitted after provider completion.
- `LIVE`: Low-latency time-to-first-token streaming where provider chunks are yielded immediately.

A timeout around a synchronous Python tool stops waiting but cannot terminate its worker thread. Tools that perform side effects remain responsible for idempotency and cooperative cancellation. Prompts are not authorization controls.

## 0.21 scope clarification

Integrated recovery requires the SQLite execution journal, not merely the presence
of a CheckpointStore. See [recovery](operations/recovery.md) for ownership, state,
budget and unknown-effect limitations. Token accounting is observed after calls;
it is not a hard pre-call monetary ceiling. Beta minors may break APIs.
