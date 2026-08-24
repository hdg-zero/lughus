# MCP Integration Guide

The Model Context Protocol (MCP) allows Lughus agents to dynamically interact with external, standardized tool servers. Our integration is designed to be policy-ready and secure by default.

## Architecture
The integration uses an adapter pattern (`lughus.interfaces.mcp`) to prevent Lughus from tightly coupling to any specific underlying SDK.
- The `MCPClient` is a protocol defining tool discovery and invocation.
- `MCPAdapter` wraps the client, applying runtime constraints and bridging MCP tool definitions into Lughus's native `ToolPolicy` and execution layers.

## Server Configuration
When connecting to a remote MCP server, you must provide an `MCPServerConfig`.
- **HTTPS Only:** For security, the server origin must be an HTTPS URL with no credentials, path, query, or fragments.
- **Allowlists:** You must explicitly define an `allowed_tools` set. Tools advertised by the server that are not in this list are ignored.
- **Limits:** Hard limits on the maximum number of tools and maximum output characters are enforced to prevent memory exhaustion.

## Conservative Metadata
Because remote tools run outside of Lughus's control, `MCPAdapter.conservative_metadata()` assigns strict defaults:
- **Effect:** Treated as `EXTERNAL`.
- **Risk:** Marked as `UNKNOWN`.
- **Approval:** Requires human approval (`requires_approval=True`) by default.
- **Concurrency:** Enforced as `SERIAL_PER_TOOL` to prevent unexpected race conditions on the remote end.

## Governance and Invocation

All MCP tool invocations pass through the standard Lughus governance pipeline
(policy, approval, idempotency, budget). The `MCPAdapter._invoke` method is
**internal** and must never be called directly by application code. The leading
underscore signals this intent.

**Why is `_invoke` private?**
A public `invoke` method would let callers bypass every governance layer the
framework provides -- policy checks, human approval, idempotency guards, and
budget enforcement. By keeping invocation internal, the only path to execute an
MCP tool is through `register_tools`, which wires each tool into the normal
`ToolRuntime._execute_tools` pipeline where all governance applies.

### Schema fingerprinting

At `refresh()` time, `MCPAdapter` computes a SHA-256 fingerprint of every
tool's input and output schemas. Before each `_invoke` call, the fingerprint
is recomputed and compared. If the remote server has altered its schemas
mid-run (e.g., adding a dangerous parameter), the call is refused with a
`RuntimeError` rather than executing against an unvalidated schema. To recover,
call `refresh()` again to accept the new schemas explicitly.

## Security Considerations
- Lughus takes a snapshot of the permitted tool definitions during discovery. If the remote server alters a tool signature mid-run, it will be rejected via the schema fingerprint check.
- Avoid passing sensitive Lughus tokens to the MCP layer. Treat all data returned from an MCP invocation as untrusted.
- Server-Side Request Forgery (SSRF) and malicious redirects must be mitigated by the underlying `MCPClient` implementation.

## Limitations
Currently, Lughus only supports unary RPC-style MCP interactions.
- Native standard I/O (stdio) transports are not yet supported.
- Server-Sent Events (SSE) for push notifications and streaming tool outputs are not yet supported.

```python
from lughus.interfaces.mcp import MCPServerConfig, MCPAdapter


# Mock client for demonstration
class MockClient:
    async def list_tools(self):
        return []

    async def call_tool(self, name, args):
        return {}


config = MCPServerConfig(
    origin="https://api.internal.service",
    allowed_tools=frozenset({"fetch_data", "analyze_metrics"}),
)

adapter = MCPAdapter(MockClient(), config)
# In application startup, you would refresh the adapter:
# await adapter.refresh()
```
