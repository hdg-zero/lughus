"""Deterministic scenario evaluation over run events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ..core.domain import RunEvent


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    objective: str
    expected_terminal_event: str = "run.completed"
    required_event_types: frozenset[str] = field(default_factory=frozenset)
    forbidden_event_types: frozenset[str] = field(default_factory=frozenset)
    max_events: int = 1_000
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    scenario: str
    passed: bool
    failures: tuple[str, ...]
    event_count: int


async def evaluate_scenario(
    scenario: Scenario,
    execute: Callable[[Scenario], Awaitable[Sequence[RunEvent]]],
) -> EvaluationResult:
    events = tuple(await execute(scenario))
    types = {event.type for event in events}
    failures: list[str] = []
    if len(events) > scenario.max_events:
        failures.append(f"event count {len(events)} exceeds {scenario.max_events}")
    missing = scenario.required_event_types - types
    if missing:
        failures.append(f"missing events: {','.join(sorted(missing))}")
    forbidden = scenario.forbidden_event_types & types
    if forbidden:
        failures.append(f"forbidden events: {','.join(sorted(forbidden))}")
    if not events or events[-1].type != scenario.expected_terminal_event:
        failures.append(f"terminal event must be {scenario.expected_terminal_event}")
    sequences = [event.sequence for event in events]
    if sequences != sorted(set(sequences)):
        failures.append("event sequences are not unique and monotonic")
    return EvaluationResult(scenario.name, not failures, tuple(failures), len(events))
