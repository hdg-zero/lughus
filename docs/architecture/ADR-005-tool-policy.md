# ADR-005: Tool capabilities, policy engine, and human approvals

* **Status:** accepted
* **Date:** 2026-07-25
* **Authors:** hdg-zero

---

## 1. Context and Problem Statement

In early agent frameworks, tool calling relied primarily on system prompts to dictate authorization boundaries and safety constraints. LLMs were expected to respect instructions such as *"Do not execute write commands without user permission"*.

This prompt-based authorization model suffers from severe security flaws:
1. **Prompt Injection & Overreliance:** Malicious or malformed inputs can bypass prompt instructions, triggering unauthorized tool calls.
2. **Lack of Determinism:** System prompts cannot guarantee hard authorization boundaries across LLM providers or stochastic generations.
3. **Implicit Side Effects:** Tools executed arbitrary actions (file writes, API calls, database modifications) without declared risk levels, scopes, or idempotency metadata.

Lughus requires a **deterministic, code-enforced authorization and approval pipeline** that operates strictly outside the model context.

---

## 2. Decision Outcome

We adopt a **governed tool architecture** (Tool Contract) composed of three core abstractions:

### A. Rich Tool Metadata (`ToolDef`)
Every registered tool declares explicit execution metadata:
- **`effects`**: `frozenset[ToolEffect]` (`READ`, `WRITE`, `EXTERNAL`, `IRREVERSIBLE`).
- **`risk`**: `ToolRisk` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, `UNKNOWN`).
- **`required_scopes`**: `frozenset[str]` required permission scopes.
- **`idempotent`**: `bool` indicating whether retries are safe.
- **`requires_approval`**: `bool` forcing human-in-the-loop validation.
- **`concurrency`**: `ConcurrencyMode` (`PARALLEL_SAFE`, `SERIAL_PER_TOOL`, `SERIAL_PER_RESOURCE`, `GLOBAL_EXCLUSIVE`).

Tools registered without explicit governance metadata default conservatively to `risk=ToolRisk.UNKNOWN`, `concurrency=ConcurrencyMode.SERIAL_PER_TOOL`, and empty scopes.

### B. Deterministic Policy Engine (`ToolPolicy`)
Authorization decisions are evaluated before dispatch by a `ToolPolicy` implementation:
- **Inputs:** `ToolProposal` (canonicalized tool name, arguments, risk, required scopes, effects) and `Principal` (subject, tenant ID, granted scopes).
- **Outputs:** `PolicyDecision` containing `DecisionKind` (`ALLOW`, `DENY`, `REQUIRE_APPROVAL`) and code/reason.
- **Precedence Rule:** `DENY` takes precedence over `REQUIRE_APPROVAL`, which takes precedence over `ALLOW`.

### C. Tamper-Evident Approvals (`ApprovalRequest` & `ApprovalStore`)
When an action requires approval (via policy decision or `requires_approval=True`):
1. A canonical SHA-256 hash of `{"tool": name, "arguments": args}` is computed (`proposal_digest`).
2. An `ApprovalRequest` is created in an `ApprovalStore` bound to this hash.
3. Execution pauses and returns a `SafeToolError("approval_required", ...)` to the loop context.
4. An approval decision (`APPROVED` or `REJECTED`) is recorded by an authenticated subject. Any argument mutation invalidates the hash signature (`verify()` fails).

---

## 3. Consequences

### Positive
- **Deterministic Security Boundary:** Prompt instructions never grant or deny authorization. Policy decisions are enforced in Python code prior to callable dispatch.
- **Tamper Evidence:** Canonical argument hashing prevents argument modification attacks between proposal and approval execution.
- **Least Privilege:** Missing scopes yield explicit `missing_scope` denials before executing any business code.

### Negative / Trade-offs
- **Principal Context Required:** Enforcing policies requires passing `Principal` context into `ToolExecutionConfig`.
- **HITL Latency:** Operations requiring approval pause execution until an out-of-band decision is submitted.
