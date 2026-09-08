# Upgrading the stacked beta releases

## 0.19

Use the same objective/principal/registry signature for governed run and stream.
Do not pass tool_config to bypass the configured runtime. Runtime stores must
share one transactional backend. Close streaming iterators on early exit.

## 0.20

Import engine/interfaces from their owning modules. Configure an explicit
ContainerPythonBackend and BinaryArtifactStore; remove calls to run_python.
Provision a digest-pinned image on the worker. Stdio MCP environments must be
supplied explicitly when tools require credentials. Pin supported protocol
bindings rather than assuming every MCP/A2A revision is compatible.

## 0.21

A ToolDef now retains its inferred Pydantic input model. Policies and receipts use
canonical JSON; callables receive hydrated Python objects. Annotated constraints
are preserved. For explicit manual JSON schemas, callable arguments remain JSON
unless an input model is explicitly provided on ToolDef.

Use SQLiteStore + SQLiteApprovalStore + AgentRuntime(journal=store) for integrated
resumption. Durable tools must not accept injected mutable state. Receipt identity
is invocation-scoped, not a cache across arbitrary equal-argument calls. Use the
same invocation ID when replaying the same attempt in low-level tests. Import
non-root governance contracts from their owning modules.

Tool failures settle/release their reservations. Budget exhaustion stops execution
rather than becoming a model-retryable tool result. Unknown effects suspend
execution for reconciliation. See the recovery guide for operational boundaries.

No compatibility shims, implicit store migrations, image auto-pulls, transport
auto-replays or fake sandbox fallback are retained.
