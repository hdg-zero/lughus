# Threat model

User objectives, uploaded files, model output, tool output, MCP servers and remote agents are
untrusted. Runtime policy and authenticated principals are trusted only after validation.
Prompts do not cross the authorization boundary.

Prompt injection may propose excessive tool use; policies and approvals constrain effects.
Unknown tool diagnostics are redacted. The test UI is disabled in production and does not
follow trace-endpoint redirects. Process-local limits do not replace cluster ingress controls.
Synchronous timed-out tools may continue and therefore require idempotency for effects.
