# Budget system

## Cost representation: integer micros

All monetary cost values in Lughus are expressed as **integer micros**
(millionths of a currency unit).  One US dollar equals `1_000_000` micros.

```
$1.00   = 1_000_000 micros
$0.01   =    10_000 micros
$0.0001 =       100 micros
```

The field is named `estimated_cost_micros` on both `BudgetLimit` (the
cap) and `BudgetAmount` (individual amounts reserved or settled).

### Why not floats?

IEEE 754 double-precision floats accumulate rounding error on repeated
addition.  After 10 000 additions of `0.0001` the sum is
`0.9999999999999062`, not `1.0`.  Budget limit comparisons on floats
(`total >= limit`) are therefore unreliable.  Integers are exact.

### Converting to display values

```python
micros = 1_234_567
dollars = micros / 1_000_000  # 1.234567 -- convert only for display
```

## Reserve / settle lifecycle

Every external action (model call, tool call) follows a three-step
protocol:

1. **Reserve** -- `BudgetLedger.reserve(amount)` atomically checks that
   the reservation plus all outstanding reservations plus consumed totals
   stay within the `BudgetLimit`.  Returns a reservation id.

2. **Execute** -- The external call proceeds.

3. **Settle or release**:
   - `settle(reservation_id, actual)` records the observed actual usage
     and frees the reservation.
   - `release(reservation_id)` frees the reservation without recording
     any usage (nothing happened).

### Idempotency

`settle()` is idempotent: calling it twice with the same reservation id
is a no-op (the second call does nothing).  This simplifies error-
handling paths that may settle defensively.

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
reservation id to `BudgetAmount`.  Use it for monitoring and debugging.
