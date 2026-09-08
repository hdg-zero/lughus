# Capability status for 0.21 beta

Implemented does not mean validated against every provider or suitable for every
production deployment. There is no compatibility guarantee between beta minors.

| Capability | Integrated path | Remaining deployment responsibility |
|---|---|---|
| run/stream governance | Shared runner and loop engine | Authenticated identity, policy and audit ACLs |
| Human approval | Suspension plus durable SQLite decisions | Reviewer authorization and expiry policy |
| Durable resumption | SQLite execution journal, same-host single owner per run | Worker termination, backup, retention, reconciliation |
| External effects | Per-invocation started/completed receipts | External idempotency or operator reconciliation |
| Runtime limits | Bounded queue/workers, writer-preferring exclusive gate | Process-local only; sync cancellation cannot kill a thread |
| Python execution | Explicit Docker/Podman backend, binary artifact store | Pinned image, Linux/cgroups, hardened host, orphan cleanup |
| A2A client | Native 0.3 JSON-RPC HTTP binding | Authentication, task polling, interoperability checks |
| MCP clients | 2024-11-05 stdio and legacy HTTP+SSE | Trusted endpoints/processes; no Streamable HTTP/OAuth support |
| Typed tools | Inferred Pydantic model retained for input hydration | Provider/schema compatibility testing |

This patch series has syntax/stdlib checks, not a certification or a claim that
all provider, container, typing or full pytest checks were run in its authoring
environment. Run the complete project checks before publishing each branch.
