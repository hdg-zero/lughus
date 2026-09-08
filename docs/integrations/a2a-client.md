# Native A2A client (0.20)

`lughus.interfaces.a2a.A2AClient` implements the **A2A 0.3 JSON-RPC HTTP binding**
using httpx, without importing the server SDK. This is a scoped binding, not a
claim of support for every A2A transport or future protocol revision.

```python
async with A2AClient("https://agent.example/rpc", headers=headers) as client:
    card = await client.agent_card()
    result = await client.send_message({
        "kind": "message", "role": "user", "messageId": uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": "Summarize this report"}],
    })
    task = await client.get_task(result["id"])
```

Methods: `send_message`, `stream_message`, `get_task`, `cancel_task`, `resubscribe`,
`agent_card`, and the RemoteAgentClient-compatible `delegate`. `delegate` returns
the remote task status, which can still be working or input-required; it does not
pretend that every response is complete. A delegation target must match the
configured endpoint exactly. Remote skill/causal metadata is informative, never
an authorization grant. Parent budgets are not automatically inherited remotely.

HTTPS is required except on loopback. No redirects, automatic effect retries,
automatic artifact downloads or cross-origin credential forwarding. Configure
trusted endpoints in the application, never directly from model output. Response
and per-event bytes are bounded. The timeout covers the whole request/stream.
Use `contextlib.aclosing` when exiting a streaming iterator early. Injected httpx
clients remain caller-owned. Applications own task polling and auth refresh.
