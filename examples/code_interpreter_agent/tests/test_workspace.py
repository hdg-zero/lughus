"""Offline tests for Code Interpreter Agent Workspace with MockLLM."""

from __future__ import annotations

from pathlib import Path

import pytest
from code_interpreter_agent.config import SandboxMode, Settings
from code_interpreter_agent.workspace import Workspace

from lughus import CompletionEvent, ProgressEvent, ToolExecutionConfig
from lughus.testing import MockLLM


@pytest.mark.asyncio
async def test_workspace_execution_with_mock_llm(tmp_path: Path) -> None:
    settings = Settings(
        sandbox_mode=SandboxMode.SUBPROCESS,
        artifacts_dir=tmp_path / "artifacts",
        sandbox_memory_mb=2_048,
        sandbox_timeout_s=10.0,
    )
    tool_config = ToolExecutionConfig()

    mock_llm = MockLLM(
        [
            [
                {
                    "id": "c1",
                    "name": "code_interpreter",
                    "arguments": {
                        "code": (
                            'open("correlation.png", "wb").write(b"PNG_CONTENT")\n'
                            'print("Analysis complete.")'
                        ),
                    },
                }
            ],
            "I have analyzed the metrics and produced the correlation plot correlation.png.",
        ]
    )

    workspace = Workspace(
        objective="Analyze correlation and generate plot.",
        files=[],
        llm=mock_llm,
        settings=settings,
        tool_config=tool_config,
    )

    events = [event async for event in workspace.run()]

    assert any(isinstance(e, ProgressEvent) for e in events)
    completion = next(e for e in events if isinstance(e, CompletionEvent))
    assert "correlation.png" in completion.text
    assert len(completion.artifacts) == 1
    assert completion.artifacts[0].name == "correlation.png"
    assert completion.metadata["artifact_count"] == 1
    assert completion.metadata["budget_usage"]["model_calls"] == 2


@pytest.mark.asyncio
async def test_workspace_marks_attachments_as_external_context(tmp_path: Path) -> None:
    settings = Settings(
        sandbox_mode=SandboxMode.SUBPROCESS,
        artifacts_dir=tmp_path / "artifacts",
        sandbox_memory_mb=2_048,
        sandbox_timeout_s=10.0,
    )
    mock_llm = MockLLM(["The supplied CSV contains two records."])
    workspace = Workspace(
        objective="Summarize the attachment.",
        files=[(b"name,value\nA,1\nB,2\n", "text/csv", "input.csv")],
        llm=mock_llm,
        settings=settings,
        tool_config=ToolExecutionConfig(),
    )

    _events = [event async for event in workspace.run()]

    first_messages = mock_llm.calls[0]["messages"]
    rendered = "\n".join(str(message["content"]) for message in first_messages)
    assert 'source="attachment:input.csv"' in rendered
    assert 'trust="external"' in rendered
