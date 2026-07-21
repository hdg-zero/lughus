# Tool contract v2

Tool arguments and results are JSON-Schema validated. Effects describe read/write/external and
irreversible behavior. Risk and scopes feed policy decisions. Idempotence is an explicit business
guarantee, not inferred from HTTP methods or function names. Approval binds the exact canonical
hash of tool name and arguments; changing either invalidates it.
