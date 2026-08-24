# Evaluations and Replay Guide

Testing non-deterministic A2A agents presents a unique challenge. Lughus separates testing into two distinct phases: deterministic replay of past interactions, and probabilistic evaluation of scenario constraints.

## Development Cycle Overview
The `lughus.persistence.replay` and `lughus.testing.evaluation` modules allow you to capture an agent's execution, seal it into a portable bundle, and run assertions against the resulting event stream. This ensures regressions are caught early without incurring the cost and variance of live LLM calls.

## Replay Bundles
A `ReplayBundle` encapsulates everything needed to reconstruct a `Run`.
- **Sealing & Serialization:** Bundles must be explicitly sealed via `bundle.seal()`, which computes an SHA-256 integrity hash over the canonical JSON representation.
- **Integrity Verification:** Deserializing a bundle with `ReplayBundle.from_json` automatically verifies the hash. If the payload is modified, it raises a `ValueError`.
- **Modes:** Bundles can be replayed in strict mode (all calls must match exactly) or comparison mode (for evaluating new prompts against old data).

## Scenario Evaluation
The `Scenario` dataclass defines the boundary conditions for an agent test. You define the required events, forbidden events, and the expected terminal state.

```python
import asyncio
from lughus.testing.evaluation import Scenario, evaluate_scenario


async def execute_mock_run(scenario: Scenario):
    # In a real test, this would invoke the agent with a Mock or Replay transport
    from lughus.core.domain import RunEvent

    return [
        RunEvent(run_id="run_1", type="run.started", sequence=1),
        RunEvent(run_id="run_1", type="tool_call", sequence=2),
        RunEvent(run_id="run_1", type="run.completed", sequence=3),
    ]


async def main():
    scenario = Scenario(
        name="Test Tool Execution",
        objective="Ensure agent calls a tool and completes",
        expected_terminal_event="run.completed",
        required_event_types=frozenset({"run.started", "tool_call"}),
        forbidden_event_types=frozenset({"run.failed"}),
        max_events=10,
    )

    result = await evaluate_scenario(scenario, execute_mock_run)
    print(f"Passed: {result.passed}")
    if not result.passed:
        print(f"Failures: {result.failures}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Deterministic vs Probabilistic
- **Deterministic:** Use `ReplayBundle` to ensure that given the exact same HTTP responses, your agent framework parses and executes identically.
- **Probabilistic:** Use `Scenario` with live models to ensure that regardless of the exact path the LLM takes, the agent never triggers forbidden events and always reaches the required outcomes within the event budget.
