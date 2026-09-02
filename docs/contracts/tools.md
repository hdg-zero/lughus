> [← Documentation index](../index.md)

# Tool Contract

This specification defines the formal contract for tool registration, policy evaluation, and human-in-the-loop approvals in `lughus`.

> **Contract stability:** This specification is stable. Future changes follow standard SemVer policy (ADR-001).

---

## 1. Tool Metadata Contract (`ToolDef`)

Every tool registered in `ToolRegistry` contains formal execution metadata:

| Field | Type | Description | Default |
|:---|:---|:---|:---|
| `name` | `str` | Unique tool identifier | Required |
| `description` | `str` | Tool description sent to LLM | Required |
| `fn` | `Callable` | Async or sync Python implementation | Required |
| `parameters_schema` | `dict` | Draft 2020-12 JSON Schema for input arguments | Required |
| `output_schema` | `dict \| None` | Optional Draft 2020-12 JSON Schema for tool return value | `None` |
| `version` | `str` | Tool version string | `"1"` |
| `effects` | `frozenset[ToolEffect]` | Set of `ToolEffect` (`READ`, `WRITE`, `EXTERNAL`, `IRREVERSIBLE`) | `frozenset()` |
| `risk` | `ToolRisk` | `ToolRisk` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, `UNKNOWN`) | `ToolRisk.UNKNOWN` |
| `required_scopes` | `frozenset[str]` | Required permission scopes for authorization | `frozenset()` |
| `idempotent` | `bool` | Explicit business guarantee for retry safety | `False` |
| `requires_approval` | `bool` | Flag requiring human approval prior to dispatch | `False` |
| `concurrency` | `ConcurrencyMode` | `PARALLEL_SAFE`, `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, or `GLOBAL_EXCLUSIVE` | `PARALLEL_SAFE` |

---

## 2. Policy Evaluation Flow

When `ToolExecutionConfig.policy` is set, pre-dispatch evaluation proceeds as follows:

```
                  ┌───────────────────────────────┐
                  │ Tool Proposal & Principal     │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │ Policy.evaluate(proposal, p) │
                  └───────────────┬───────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │ (kind == DENY)         │ (REQUIRE_APPROVAL)      │ (ALLOW)
         ▼                        ▼                        ▼
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ ToolExecution   │      │ ApprovalRequest │      │ Execute Tool    │
│ Error (Denied)  │      │ created & error │      │ Callable        │
└─────────────────┘      └─────────────────┘      └─────────────────┘
```

1. **Proposal Construction:** `ToolProposal` is constructed from `run_id`, `tool_name`, `arguments`, `effects`, `risk`, and `required_scopes`.
2. **Principal Requirement:** If `policy` is configured but `principal` is `None`, execution raises `ToolExecutionError`.
3. **Evaluation:** `policy.evaluate(proposal, principal)` returns `PolicyDecision`.
4. **Denial:** `DecisionKind.DENY` immediately halts execution and returns JSON error payload with code `tool_policy_denied`.
5. **Approval:** `DecisionKind.REQUIRE_APPROVAL` or `requires_approval=True` creates an `ApprovalRequest` in `ApprovalStore` and raises `SafeToolError("approval_required", ...)`.

---

## 3. Human Approval Lifecycle

```
          ┌─────────────┐
          │   PENDING   │
          └──────┬──────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
  ┌──────────┐      ┌──────────┐
  │ APPROVED │      │ REJECTED │
  └──────────┘      └──────────┘
```

1. **Digest Calculation:** `proposal_digest(tool_name, arguments)` computes `SHA-256(sort_keys_json({"tool": tool_name, "arguments": arguments}))`.
2. **Verification:** `request.verify(arguments)` re-computes digest; returns `False` if arguments were modified.
3. **State Transition:** `store.decide(request_id, status, subject)` transitions `PENDING` to `APPROVED` or `REJECTED`. Transitions from terminal states raise `ValueError`.

---

## 4. Error Payload Formats

Errors returned to the agent loop follow structured JSON payloads:

```json
{
  "error": "Human approval is required (request_id=approval_12345)",
  "error_code": "approval_required",
  "retryable": false
}
```

```json
{
  "error": "Tool policy denied action: missing_scope",
  "error_code": "ToolExecutionError",
  "retryable": false
}
```

---

**Related:** [Tools API](../api/tools.md) · [Tools Guide](../guides/tools.md)
