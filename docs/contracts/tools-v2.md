# Tool contract v2

Tool arguments and results are JSON-Schema validated. Effects describe read/write/external and
irreversible behavior. Risk and scopes feed policy decisions. Idempotence is an explicit business
guarantee, not inferred from HTTP methods or function names. Approval binds the exact canonical
hash of tool name and arguments; changing either invalidates it.

When `ToolExecutionConfig.policy` is set, execution requires an authenticated principal. A denied
action never reaches the callable. An approval decision creates a request bound to the canonical
proposal hash and returns a stable `approval_required` model-visible error; applications resume the
run only after an authenticated decision.
