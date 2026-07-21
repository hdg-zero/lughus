# ADR-003: Runtime resource ownership

Status: accepted

Executors, semaphores and shutdown belong to an explicit application ExecutionRuntime.
There is no first-caller-wins process global. Sharing a runtime is deliberate; isolation
requires distinct runtimes.
