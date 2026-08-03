# Scaling Guide

Lughus is built as a lightweight framework. Moving from a local development environment to a multi-replica production deployment requires understanding the underlying persistence and concurrency guarantees.

## Single Process Execution
Locally, Lughus handles concurrency via the `ExecutionRuntime` (`lughus.runtime`).
- It manages an isolated `ThreadPoolExecutor` dedicated strictly to tool execution.
- Global semaphores prevent aggressive LLMs from overwhelming the host with parallel tool calls.
- In-memory event sinks handle subscription state.

## Multi-Replica Deployments
When scaling out horizontally across multiple workers or containers, the in-memory runtime is insufficient.
- You must provide concrete implementations for the `RunStore` and `EventStore` protocols (`lughus.persistence`).
- The framework requires that these stores support **atomic updates** (e.g., via optimistic concurrency control using the `version` field). If two workers attempt to modify the same run, one must cleanly fail with a `ConcurrentUpdateError`.

## Distributed Locks
Lughus does not implement distributed locking natively. The included `InMemoryRunStore` is explicitly for testing and development. For production, applications must implement a backend (like PostgreSQL, Redis, or DynamoDB) that can enforce transactional consistency over the event sequence.

## Current Limitations
- There is currently no native framework support for rebalancing active runs if a worker node dies unexpectedly. This relies on the surrounding infrastructure (like Kubernetes) and the polling/resume logic.
- Long-polling subscriptions over the event stream currently require sticky sessions or an external pub/sub mechanism like Redis Streams to broadcast events across replicas.
