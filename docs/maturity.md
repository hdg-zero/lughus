# Capability status (Beta)

Implemented does not mean validated against every provider or suitable for every
production deployment. There is no backward compatibility guarantee between beta versions.

| Capability | Integrated path | Remaining deployment responsibility |
|---|---|---|
| run/stream governance | Shared runner and loop engine | Authenticated identity, policy and audit ACLs |
| Human approval | Suspension plus durable SQLite decisions | Reviewer authorization and expiry policy |
| Durable resumption | SQLite execution journal, same-host single owner per run | Worker termination, backup, retention, reconciliation |
| External effects | Per-invocation started/completed receipts | External idempotency or operator reconciliation |
| Runtime limits | Bounded queue/workers, writer-preferring exclusive gate | Process-local only; sync cancellation cannot kill a thread |
| Runtime hardening | Explicit runtime invariant checks, token cache eviction, ASGI body cutoff | Host process quotas and cluster ingress controls |
| Python execution | Explicit Docker/Podman backend, binary artifact store | Pinned image, Linux/cgroups, hardened host, orphan cleanup |
| A2A client | Native 0.3 JSON-RPC HTTP binding | Authentication, task polling, interoperability checks |
| MCP clients | 2024-11-05 stdio and legacy HTTP+SSE | Trusted endpoints/processes; no Streamable HTTP/OAuth support |
| Typed tools | Inferred Pydantic model retained for input hydration | Provider/schema compatibility testing |

This framework includes syntax and stdlib validation, but operators remain responsible
for comprehensive environment testing. Run the complete project checks before deploying.

