# ADR-004: Run/Event Model

## Context
As an A2A micro-framework, Lughus requires a structured, observable execution journal to trace complex AI behaviors. The runtime demands a mechanism to reliably capture everything an agent does to enable execution resumption across process boundaries, detailed audits, and real-time streaming to user interfaces. We needed to choose a data model that encapsulates this execution state without becoming tightly coupled to a specific underlying persistence backend.

## Decision
We adopted an event-sourced execution model organized around the `Run` and `RunEvent` constructs (`lughus.domain`).
- **Run Status:** The high-level state is defined by the `RunStatus` enumeration, transitioning from `PENDING` and `RUNNING` to terminal statuses like `COMPLETED`, `FAILED`, or `CANCELLED`. Once terminal, the `Run` cannot transition further.
- **Events:** Execution history is tracked via immutable `RunEvent` instances that form a strictly monotonic sequence per `Run`.
- **Visibility:** We implemented a 4-level visibility system (`EventVisibility`: `INTERNAL`, `MODEL`, `PUBLIC`, `AUDIT`) to control exposure of event data.

## Alternatives
- **Generic DAG:** We evaluated modeling executions as a Directed Acyclic Graph (DAG), but deemed it too complex for the initial release. It introduced significant overhead in state tracking.
- **Mutable Events:** We considered allowing updates to past events. This was rejected because it fundamentally breaks replayability and makes reliable real-time event streaming impossible.

## Consequences
- The monotonic sequence guarantee places the burden of ordering enforcement squarely on the underlying EventStore implementations.
- Projections (like generating a user-friendly A2A stream or mapping Server-Sent Events) must be derived lazily from the append-only event log.
- High throughput applications may need to implement event batching to mitigate database insert pressure on the strictly ordered journal.

## Compatibility
The event schema is strictly versioned (`SCHEMA_VERSION = "1.0"`). Future modifications to the event structure must be purely additive or introduce a new major version, ensuring backwards compatibility when reading older execution journals.

## Security
By utilizing `EventVisibility`, sensitive internal tooling or prompt mechanics are separated from the public stream by default. Downstream clients receive only the data meant for their respective layers.
