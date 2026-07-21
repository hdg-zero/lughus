# Guarantees and non-guarantees

Lughus validates tool inputs and bounds configured payloads. Limits are scoped to one
application runtime unless explicitly documented otherwise. The in-memory task store is
not durable and is not suitable for multiple replicas.

`agent_loop_stream` in 0.1.x is retry-safe but buffered: final text is emitted only after
the provider stream completes. It is not a time-to-first-token API. Live at-most-once
streaming is introduced as an explicit mode in 0.2.0.

A timeout around a synchronous Python tool stops waiting but cannot terminate its worker
thread. Tools that perform side effects remain responsible for idempotency and cooperative
cancellation. Prompts are not authorization controls.
