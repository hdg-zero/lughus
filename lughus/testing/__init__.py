"""Test utilities and evaluation framework."""

from .evaluation import EvaluationResult, Scenario, evaluate_scenario
from .mocks import (
    FakeChoice,
    FakeChunk,
    FakeDelta,
    FakeFunction,
    FakeFunctionDelta,
    FakeMessage,
    FakePromptTokensDetails,
    FakeResponse,
    FakeStreamChoice,
    FakeToolCall,
    FakeToolCallDelta,
    FakeUsage,
    MockLLM,
    MockStreamingLLM,
    _make_streaming_chunk,
)

__all__ = [
    "EvaluationResult",
    "FakeChoice",
    "FakeChunk",
    "FakeDelta",
    "FakeFunction",
    "FakeFunctionDelta",
    "FakeMessage",
    "FakePromptTokensDetails",
    "FakeResponse",
    "FakeStreamChoice",
    "FakeToolCall",
    "FakeToolCallDelta",
    "FakeUsage",
    "MockLLM",
    "MockStreamingLLM",
    "Scenario",
    "evaluate_scenario",
]
