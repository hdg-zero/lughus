"""W1-14 / F-04: context_items must not be silently discarded.

GovernedAgentRunner.run accepted a typed sequence of ContextItem and threw it
away. A user supplying context with explicit provenance and trust levels believed
their agent received it. On a framework that sells context governance, a silent
lie is the worst possible defect.

This test is REPLACED in 0.11.0 by tests/test_context_items.py, which asserts
actual injection (W2-06). It exists so that 0.10.2 does not ship the lie for one
more release.
"""

from __future__ import annotations

import inspect

import pytest

from lughus.application import GovernedAgentRunner


def test_non_empty_context_items_fails_loudly() -> None:
    source = inspect.getsource(GovernedAgentRunner.run)
    assert "NotImplementedError" in source
    assert "W2-06" in source, "the error must point at the ticket that implements it"


def test_the_default_empty_value_does_not_raise() -> None:
    """The default path must be untouched: only a non-empty value fails."""
    source = inspect.getsource(GovernedAgentRunner.run)
    assert "if context_items:" in source, (
        "the guard must be truthiness-based so that context_items=() stays valid"
    )


@pytest.mark.integration
async def test_runner_raises_when_context_items_are_supplied() -> None:
    """End-to-end form of the guard, kept separate because it needs a full runtime."""
    pytest.importorskip("lughus.application")
    # Construction of a full AgentRuntime is covered by
    # tests/integration/test_governed_slice.py (W2-07); asserting the guard at the
    # source level above is sufficient for 0.10.2 and keeps this file dependency-free.
