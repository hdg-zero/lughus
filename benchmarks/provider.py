"""Replay/mock LLM provider for deterministic benchmarks without network calls.

Uses lughus.testing.MockLLM which implements both the GenerateLLM protocol
(via ``generate()``) for the agent_loop. No network traffic occurs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lughus.testing import MockLLM


def build_mock_llm(responses: Sequence[Any]) -> MockLLM:
    """Build a MockLLM pre-loaded with scripted responses.

    Parameters
    ----------
    responses:
        A sequence where each element is either:
        - ``str`` -- text response (terminates the loop)
        - ``list[dict]`` -- tool call response with keys ``name``, ``arguments``, ``id``
    """
    return MockLLM(responses)
