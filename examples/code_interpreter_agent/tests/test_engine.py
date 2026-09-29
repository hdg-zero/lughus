"""Tests for the sandboxed execution engines and artifact exports."""

from __future__ import annotations

from pathlib import Path

import pytest
from code_interpreter_agent.config import SandboxMode, Settings
from code_interpreter_agent.engine import DataScienceEngine, IsolatedSubprocessBackend


@pytest.mark.asyncio
async def test_subprocess_backend_captures_stdout() -> None:
    backend = IsolatedSubprocessBackend(timeout_s=10.0)
    result = await backend.execute("print('Data Science initialized')\nprint(2 + 2)")
    assert result.exit_code == 0
    assert "Data Science initialized" in result.stdout
    assert "4" in result.stdout


@pytest.mark.asyncio
async def test_subprocess_backend_captures_artifacts() -> None:
    backend = IsolatedSubprocessBackend(timeout_s=10.0)
    # Simulate generating a plot file
    code = """\
with open("plot.png", "wb") as f:
    f.write(b"\\x89PNG\\r\\n\\x1a\\nfake_png_data")
with open("data.csv", "w") as f:
    f.write("a,b\\n1,2\\n")
print("Files written successfully")
"""
    result = await backend.execute(code)
    assert result.exit_code == 0
    assert len(result.files) == 2
    filenames = {art.name for art in result.files}
    assert "plot.png" in filenames
    assert "data.csv" in filenames

    # Verify mime types
    plot_art = next(art for art in result.files if art.name == "plot.png")
    assert plot_art.mime_type == "image/png"
    assert plot_art.data.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_subprocess_backend_blocks_network() -> None:
    backend = IsolatedSubprocessBackend(timeout_s=10.0)
    result = await backend.execute("import socket\ns = socket.socket()")
    assert result.exit_code != 0
    assert "Network access disabled" in result.stderr


@pytest.mark.asyncio
async def test_data_science_engine_persists_artifacts(tmp_path: Path) -> None:
    settings = Settings(
        sandbox_mode=SandboxMode.SUBPROCESS,
        artifacts_dir=tmp_path / "artifacts",
        sandbox_memory_mb=2_048,
        sandbox_timeout_s=10.0,
    )
    engine = DataScienceEngine(settings)

    code = 'open("report.png", "wb").write(b"PNGDATA")\nprint("DONE")'
    result, file_refs = await engine.run_code(code)

    assert result.exit_code == 0
    assert len(file_refs) == 1
    ref = file_refs[0]
    assert ref["name"] == "report.png"
    assert (tmp_path / "artifacts" / ref["artifact_id"]).exists()


def test_container_mode_requires_an_immutable_image() -> None:
    with pytest.raises(ValueError, match="CONTAINER_IMAGE"):
        Settings(sandbox_mode=SandboxMode.CONTAINER, container_image="python:3.12-slim")


def test_production_rejects_the_development_backend() -> None:
    with pytest.raises(ValueError, match="forbidden in production"):
        Settings(sandbox_mode=SandboxMode.SUBPROCESS, environment="production")
