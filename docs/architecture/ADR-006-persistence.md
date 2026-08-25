> [← Documentation index](../index.md)

# ADR-006: Persistence and safe resumption

Status: accepted

Run state, append-only events and checkpoints are separate ports even when one backend implements
all three. Updates use optimistic versions. Checkpoints identify pending actions and unknown
outcomes. A non-idempotent unknown outcome requires reconciliation and is never retried silently.
The bundled in-memory implementation is atomic for tests but explicitly not durable.
