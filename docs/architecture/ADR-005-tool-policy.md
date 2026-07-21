# ADR-005: Tool capabilities and policy

Status: accepted

Tools declare input/output schemas, effects, risk, scopes, idempotence, approval and concurrency.
Unknown legacy tools are treated conservatively. A deterministic ToolPolicy runs before an action;
deny takes precedence. High-risk or irreversible actions require a tamper-evident approval. Prompt
instructions never grant authority.
