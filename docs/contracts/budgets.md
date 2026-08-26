# Run Budgets Contract

> **Contract stability:** This specification is stable. Future changes follow standard SemVer policy (ADR-001).

## Architecture

Budget governance follows a reserve/settle model:

| Component | Role |
|---|---|
| `BudgetLimit` | Defines maximum allowed values per dimension (policy) |
| `BudgetAmount` | Individual amounts reserved or settled |
| `BudgetLedger` | Reserves before dispatch, records observed actual usage (truth) |

## Dimensions

Budgets track the following dimensions:

| Dimension | Unit | Notes |
|---|---|---|
| Model calls | count | Per LLM invocation |
| Tool calls | count | Per tool execution |
| Tokens | count | Prompt + completion tokens reported by the provider |
| Delegation depth | level | Maximum nesting, not cumulative |

## Lifecycle

1. **Reserve** — `BudgetLedger.reserve()` atomically checks that consumed
   totals plus all outstanding reservations plus the requested amount stay
   within `BudgetLimit`. Raises `BudgetExceeded` otherwise.
2. **Execute** — Model call or tool invocation proceeds.
3. **Settle** — `BudgetLedger.settle(reservation_id, actual)` frees the
   reservation and records actual consumption. Returns `False` if the
   reservation id is unknown, making double-settles observable.
   Alternatively, `release(reservation_id)` frees a reservation without
   recording any usage (nothing happened).

Delegation depth is settled as a maximum (`max(consumed, actual)`), not a
sum: it tracks nesting level in the causal chain.

## Invariants

- Exhaustion is a typed terminal condition (`BudgetExceeded`) or an
  explicit approval request, never silently ignored.
- Cost values are estimates, not billing records.
- Delegation depth tracks maximum nesting level in the causal chain,
  not cumulative sequential calls.
