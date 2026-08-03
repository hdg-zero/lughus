# Capability maturity matrix — 0.10.0

| Capability | Implemented | Integrated | Enforced by AgentRuntime | Production dependency |
|---|---:|---:|---:|---:|
| Execution runtime | yes | yes | yes | none |
| Policy/principal | yes | yes | yes | identity resolver |
| Approval | yes | yes | yes | durable ApprovalStore |
| Atomic idempotency claim | yes | yes | yes | durable IdempotencyStore |
| Resource serialization | yes | yes | yes | distributed lock for multi-replica |
| Transactional transitions | yes | yes | yes | RunUnitOfWork backend |
| Budget/context | yes | yes | yes | persistent ledger/artifact store |
| MCP/A2A adapters | yes | ToolRegistry | yes | authenticated transports |
| Replay redaction/signature | yes | optional capture | policy-dependent | key management |

In-memory stores are compliance references and do not qualify a multi-replica deployment. Legacy
loop APIs remain compatible but governance is mandatory only through AgentRuntime.
