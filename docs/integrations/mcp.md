# Native MCP transports (0.20)

Supported binding: MCP **2024-11-05 stdio and legacy HTTP+SSE**. Streamable HTTP,
OAuth discovery, sampling and server-initiated client requests are not implemented.
Unsupported negotiated protocol versions fail explicitly, rather than appearing
compatible. A2A is separately documented in [a2a-client.md](a2a-client.md).

MCPAdapter exposes an explicit allowed-tools snapshot. `refresh()` approves it;
register the resulting ToolDefs in the registry. Tool-list changes invalidate the
cache. Descriptor drift blocks execution until explicitly refreshed and the
registry rebuilt. Treat descriptions and returned content as untrusted input.
`structuredContent` is preserved, `isError` raises a safe local tool error and
multimodal content is not silently discarded. Discovery follows bounded pages.

Stdio runs a trusted executable without a shell. It is NOT a sandbox. The default
environment contains PATH only; explicitly supply any necessary credentials.
Both stdout and stderr are drained; requests, responses and outstanding calls
are bounded. Closing terminates the child and fails all pending requests.

SSE pins POST endpoints to the original scheme, host and port. No redirects or
cross-origin credentials are permitted. Multi-line events are parsed with bounded
buffers. Correlation is registered before sending, so immediate SSE replies are
not lost. A deadline covers the complete logical operation, including waiting for
its SSE response. Disconnects fail outstanding requests. There is deliberately no
automatic reconnect/replay of actions with uncertain outcomes: reconcile first.
Injected HTTP clients are caller-owned. Always close clients or use `async with`.
