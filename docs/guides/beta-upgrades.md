# Beta Runtime Conventions and Architecture

Lughus is in beta. There is no backward compatibility guaranteed between beta
releases. No compatibility shims, implicit store migrations, image auto-pulls,
transport auto-replays or fake sandbox fallbacks are retained.

## Governed Execution and Shared Engine

Use the same objective, principal, and registry signatures for governed run and stream.
Do not pass tool execution configurations to bypass the configured runtime. Runtime stores
must share one transactional backend. Close streaming iterators on early exit.

## Confined Execution and External Protocols

Import engine and interfaces from their owning modules. Configure an explicit
`ContainerPythonBackend` and `BinaryArtifactStore`; direct unconfined execution is forbidden.
Provision a digest-pinned image on the worker. Stdio MCP environments must be supplied
explicitly when tools require credentials. Supported protocol bindings are pinned rather
than assuming every MCP or A2A revision is compatible.

## Typed Tool Definitions and Resumption

A `ToolDef` retains its inferred Pydantic input model. Policies and receipts use
canonical JSON; callables receive hydrated Python objects. Annotated constraints
are preserved. For explicit manual JSON schemas, callable arguments remain JSON
unless an input model is explicitly provided on `ToolDef`.

Use `SQLiteStore` + `SQLiteApprovalStore` + `AgentRuntime(journal=store)` for integrated
resumption. Durable tools must not accept injected mutable state. Receipt identity
is invocation-scoped, not a cache across arbitrary equal-argument calls.

Tool failures settle or release their reservations. Budget exhaustion stops execution
rather than becoming a model-retryable tool result. Unknown effects suspend
execution for reconciliation. See the recovery guide for operational boundaries.

## Runtime Invariants and Hardening

Production invariants do not rely on `assert` statements; explicit runtime
exceptions (`RuntimeError`, `ValueError`) are raised uniformly across persistence,
governance, and transports, guaranteeing enforcement under `python -O`.

MCP client transports dynamically resolve `clientInfo` version from package metadata
and safely handle transport stream exhaustion without assertion errors.

The message history manager purges evicted message identities from the token cache
upon context pruning, preventing unbounded memory growth and identifier-reuse
collisions in long-running loops.

The ASGI production guard terminates incoming HTTP request streams immediately
upon exceeding `MAX_HTTP_BODY_BYTES`, even when response headers have already
started emitting.

