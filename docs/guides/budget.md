> [← Documentation index](../index.md)

# Budget system

## Dimensions

`BudgetLimit` (the cap) and `BudgetAmount` (individual amounts reserved or
settled) carry four integer dimensions:

| Dimension | Meaning |
|---|---|
| `model_calls` | Number of LLM invocations |
| `tool_calls` | Number of tool executions |
| `tokens` | Prompt + completion tokens reported by the provider |
| `delegation_depth` | Maximum delegation nesting level |

All values are integers: budget comparisons are exact, with no
floating-point rounding error. `delegation_depth` is settled as a maximum
(`max(consumed, actual)`), never summed -- it tracks nesting, not call count.

## Reserve / settle lifecycle

Every external action (model call, tool call) follows a three-step
protocol:

1. **Reserve** -- `BudgetLedger.reserve(amount)` atomically checks that
   consumed totals plus all outstanding reservations plus the requested
   amount stay within the `BudgetLimit`.  Returns a reservation id, or
   raises `BudgetExceeded`.

2. **Execute** -- The external call proceeds.

3. **Settle or release**:
   - `settle(reservation_id, actual)` records the observed actual usage
     and frees the reservation.  Returns `True`.
   - `release(reservation_id)` frees the reservation without recording
     any usage (nothing happened).  Returns `True`.

### Observability of accounting errors

Both methods return `False` when the reservation id does not match an
outstanding reservation (double-settle, settle-after-release,
double-release).  Treat a `False` return as an accounting bug in the
caller rather than ignoring it.

## Streaming and aborted streams

When `BudgetedLLM.astream` is used:

- **Full consumption**: all chunks consumed, then `settle()` with the
  observed token usage from the final chunk.
- **Early close (at least one chunk emitted)**: the consumer closes the
  iterator (or the task is cancelled).  Because the provider already
  billed for produced tokens, the budget is **settled** with the usage
  observed so far.
- **Early close (no chunks emitted)**: nothing was produced and the
  provider billed nothing.  The reservation is **released**.

This prevents a pattern where a loop systematically aborts streams to
spend without effective cap.

## Observability

`BudgetLedger.outstanding()` returns a snapshot of all currently
outstanding (unsettled, unreleased) reservations as a mapping of
reservation id to `BudgetAmount`.  `snapshot()` returns consumed totals
per dimension.  Use both for monitoring and debugging.

---

**Related:** [Budgets Contract](../contracts/budgets.md) · [Reliability Guide](reliability.md)
