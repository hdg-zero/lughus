# Run budgets — Frozen at 0.10.0

> **Contract stability:** This specification is frozen as of Lughus 0.10.0.
> Future changes follow the compatibility policy in ADR-001.

## Architecture

Budget governance follows a three-tier model:

| Component | Role |
|---|---|
| `BudgetLimit` | Defines maximum allowed values (policy) |
| `BudgetReservation` | Pre-dispatch authorization (reservation) |
| `BudgetLedger` | Records observed actual usage (truth) |

## Dimensions

Budgets track the following dimensions:

| Dimension | Unit | Notes |
|---|---|---|
| Model calls | count | Per LLM invocation |
| Tool calls | count | Per tool execution |
| Input tokens | count | Provider-reported |
| Output tokens | count | Provider-reported |
| Cached tokens | count | Provider-reported |
| Estimated cost | microunits | 1 microunit = 0.000001 currency unit |
| Delegation depth | level | Maximum nesting, not cumulative |

## Lifecycle

1. **Reserve** — `BudgetLedger.reserve()` atomically checks remaining
   capacity before dispatch.
2. **Execute** — Model call or tool invocation proceeds.
3. **Settle** — `BudgetLedger.settle()` records *actual* usage, which
   may exceed the reservation.

## Invariants

- The ledger **never rejects already-consumed work**. If actual usage
  exceeds the reservation, the ledger records the overage and enters
  an `over_budget` state.
- When `over_budget`, subsequent reservations are denied and the run
  halts gracefully — exhaustion is a typed terminal condition or an
  explicit approval request, never silently ignored.
- Child runs receive a bounded sub-allocation from the parent budget.
  The parent's remaining capacity is atomically reduced.
- Cost values are estimates, not billing records.
- Delegation depth tracks maximum nesting level in the causal chain,
  not cumulative sequential calls.
