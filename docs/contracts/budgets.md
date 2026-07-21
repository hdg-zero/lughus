# Run budgets

External work reserves budget before dispatch and settles actual usage afterwards. Dimensions are
model calls, tool calls, tokens, bytes, estimated cost and delegation depth. Child runs receive a
bounded sub-allocation. Cost is an estimate, not a billing record. Exhaustion is a typed terminal
condition or an explicit approval request; it is never ignored.
