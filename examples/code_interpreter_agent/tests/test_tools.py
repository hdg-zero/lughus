"""Unit tests for the Code Interpreter Agent tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from code_interpreter_agent.config import SandboxMode, Settings
from code_interpreter_agent.engine import DataScienceEngine
from code_interpreter_agent.tools import (
    create_tool_registry,
    get_environment_info,
    get_sandbox_info,
)

from lughus import ToolEffect, ToolRisk


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        sandbox_mode=SandboxMode.SUBPROCESS,
        artifacts_dir=tmp_path / "artifacts",
        sandbox_memory_mb=2_048,
        sandbox_timeout_s=10.0,
    )


@pytest.fixture
def engine(settings: Settings) -> DataScienceEngine:
    return DataScienceEngine(settings)


def test_tool_declarations(engine: DataScienceEngine, settings: Settings) -> None:
    registry = create_tool_registry(engine, settings)
    assert set(registry.names()) == {
        "code_interpreter",
        "get_environment_info",
        "get_sandbox_info",
    }

    execute = registry.get_tool("code_interpreter")
    assert execute is not None
    assert execute.risk is ToolRisk.HIGH
    assert ToolEffect.EXTERNAL in execute.effects
    assert ToolEffect.WRITE in execute.effects

    sandbox_info = registry.get_tool("get_sandbox_info")
    assert sandbox_info is not None
    assert sandbox_info.risk is ToolRisk.LOW
    assert sandbox_info.effects == frozenset({ToolEffect.READ})


def test_get_sandbox_info(engine: DataScienceEngine, settings: Settings) -> None:
    data = json.loads(get_sandbox_info(engine, settings))
    assert data["sandbox_mode"] == "subprocess"
    assert data["network_access"] is False
    assert data["container_image"] is None


@pytest.mark.asyncio
async def test_code_interpreter_basic(engine: DataScienceEngine, settings: Settings) -> None:
    registry = create_tool_registry(engine, settings)
    function = registry.get_fn("code_interpreter")
    assert function is not None
    data = await function(code="print('Hello from framework code_interpreter')")
    assert data["exit_code"] == 0
    assert "Hello from framework code_interpreter" in data["stdout"]


@pytest.mark.asyncio
async def test_code_interpreter_collects_artifacts(
    engine: DataScienceEngine,
    settings: Settings,
) -> None:
    registry = create_tool_registry(engine, settings)
    function = registry.get_fn("code_interpreter")
    assert function is not None
    code = 'open("chart.png", "wb").write(b"PNG_DATA_STREAM")\nprint("CHART SAVED")'
    data = await function(code=code)
    assert data["exit_code"] == 0
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "chart.png"
    assert [artifact.name for artifact in engine.generated_artifacts] == ["chart.png"]


@pytest.mark.asyncio
async def test_code_interpreter_strips_markdown_fence(
    engine: DataScienceEngine,
    settings: Settings,
) -> None:
    registry = create_tool_registry(engine, settings)
    function = registry.get_fn("code_interpreter")
    assert function is not None
    data = await function(code="```python\nprint('fence removed')\n```")
    assert data["exit_code"] == 0
    assert "fence removed" in data["stdout"]


@pytest.mark.asyncio
async def test_environment_info_runs_inside_sandbox(engine: DataScienceEngine) -> None:
    data = json.loads(await get_environment_info(engine))
    assert "python_version" in data
    assert "packages" in data
    assert "supported_export_formats" in data


@pytest.mark.asyncio
async def test_code_interpreter_data_science_stack(
    engine: DataScienceEngine,
    settings: Settings,
) -> None:
    registry = create_tool_registry(engine, settings)
    function = registry.get_fn("code_interpreter")
    assert function is not None
    code = """
import matplotlib.pyplot as plt
import pandas as pd

frame = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})
figure, axis = plt.subplots()
axis.plot(frame["x"], frame["y"])
plt.savefig("ds_plot.png", dpi=100)
plt.close(figure)
print(f"Sum y: {frame['y'].sum()}")
"""
    data = await function(code=code)
    assert data["exit_code"] == 0
    assert "Sum y: 60" in data["stdout"]
    assert any(file["name"] == "ds_plot.png" for file in data["files"])
    assert any(artifact.name == "ds_plot.png" for artifact in engine.generated_artifacts)
