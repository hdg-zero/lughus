> [← Documentation index](../index.md)

# Evaluations Guide

Testing non-deterministic A2A agents presents a unique challenge. Lughus separates testing into two distinct phases: deterministic offline tests with mock transports, and probabilistic evaluation of scenario constraints.

## Development Cycle Overview
The `lughus.testing` module (`MockLLM`, `MockStreamingLLM`, and `lughus.testing.evaluation`) lets you run assertions against an agent's event stream without live LLM calls. Use `MockLLM` / `MockStreamingLLM` for deterministic unit tests (see the [Testing Guide](testing.md)) and `Scenario` for probabilistic evaluation.

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
- **Deterministic:** Use `MockLLM` / `MockStreamingLLM` to ensure that given the exact same canned responses, your agent parses and executes identically.
- **Probabilistic:** Use `Scenario` with live models to ensure that regardless of the exact path the LLM takes, the agent never triggers forbidden events and always reaches the required outcomes within the event budget.
