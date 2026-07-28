# MCP integration

Only HTTPS origins and explicitly allowlisted tools are discovered. Definitions are snapshotted for
a run; a changed definition requires a new policy decision and approval. Remote tools default to
external, unknown-risk, non-idempotent and approval-required. Invocation must still pass through the
same ToolPolicy and budget path as a local tool. Client credentials are never forwarded to another
origin and redirects must be disabled or revalidated by the concrete transport.
