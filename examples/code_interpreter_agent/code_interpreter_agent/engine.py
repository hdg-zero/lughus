"""Execution backends for the Code Interpreter Agent.

Production requests are fail-closed through Lughus' OCI backend. The local
subprocess backend exists only for trusted development inputs and offline tests;
it deliberately cannot be selected in production configuration.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import shutil
import sys
import tempfile
from pathlib import Path

from lughus import (
    Artifact,
    ContainerConfig,
    ContainerPythonBackend,
    FileArtifactStore,
    InterpreterResult,
)

from .config import SandboxMode, Settings

__all__ = ["DataScienceEngine", "IsolatedSubprocessBackend"]


_ENVIRONMENT_PROBE = """\
import importlib.metadata
import json
import platform

packages = {}
for package in ("matplotlib", "numpy", "openpyxl", "pandas", "pillow", "scipy", "seaborn"):
    try:
        packages[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        packages[package] = "not installed"

print(json.dumps({"python_version": platform.python_version(), "packages": packages}))
"""


class IsolatedSubprocessBackend:
    """Best-effort local isolation for trusted development code.

    The child gets a temporary working directory, a minimal environment, Python
    isolated mode, output bounds, and an address-space limit on POSIX. It still
    shares the host user and filesystem permissions, so it is never a substitute
    for the OCI backend when code may be adversarial.
    """

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        memory_limit_mb: int = 512,
        max_code_bytes: int = 100_000,
        max_output_bytes: int = 32_000,
        max_artifact_bytes: int = 10_000_000,
        max_files: int = 10,
    ) -> None:
        limits = (
            timeout_s,
            memory_limit_mb,
            max_code_bytes,
            max_output_bytes,
            max_artifact_bytes,
            max_files,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("All subprocess sandbox limits must be positive")
        self.timeout_s = timeout_s
        self.memory_limit_mb = memory_limit_mb
        self.max_code_bytes = max_code_bytes
        self.max_output_bytes = max_output_bytes
        self.max_artifact_bytes = max_artifact_bytes
        self.max_files = max_files

    async def execute(self, code: str) -> InterpreterResult:
        """Execute trusted local code with deterministic resource bounds."""
        if len(code.encode("utf-8")) > self.max_code_bytes:
            raise ValueError("Python code exceeds the configured size limit")

        with tempfile.TemporaryDirectory(prefix="lughus-dev-sandbox-") as temporary:
            workdir = Path(temporary)
            script_path = workdir / "script.py"
            matplotlib_dir = workdir / ".matplotlib"
            matplotlib_dir.mkdir(mode=0o700)

            prelude = f"""\
import os
import socket

os.environ["MPLCONFIGDIR"] = {str(matplotlib_dir)!r}

try:
    import resource
except ImportError:
    resource = None

if resource is not None:
    limit = {self.memory_limit_mb} * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))

class _BlockedSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise OSError("Network access disabled in development sandbox")

socket.socket = _BlockedSocket

try:
    import matplotlib
except ImportError:
    pass
else:
    matplotlib.use("Agg")
"""
            script_path.write_text(prelude + "\n" + code, encoding="utf-8")
            child_env = {
                "HOME": str(workdir),
                "LANG": "C.UTF-8",
                "MPLCONFIGDIR": str(matplotlib_dir),
                "NUMEXPR_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "PATH": os.defpath,
            }
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(script_path),
                cwd=str(workdir),
                env=child_env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout_s
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return InterpreterResult(
                    stdout="",
                    stderr=f"Execution timed out after {self.timeout_s} seconds",
                    exit_code=-1,
                    files=(),
                    truncated=False,
                )
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

            artifacts = self._collect_artifacts(workdir, script_path, matplotlib_dir)
            stdout = stdout_bytes.decode("utf-8", errors="replace")[: self.max_output_bytes]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[: self.max_output_bytes]
            truncated = (
                len(stdout_bytes) > self.max_output_bytes
                or len(stderr_bytes) > self.max_output_bytes
            )
            return InterpreterResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode if process.returncode is not None else -1,
                files=tuple(artifacts),
                truncated=truncated,
            )

    def _collect_artifacts(
        self,
        workdir: Path,
        script_path: Path,
        matplotlib_dir: Path,
    ) -> list[Artifact]:
        artifacts: list[Artifact] = []
        total_bytes = 0
        candidates = [path for path in sorted(workdir.iterdir()) if path != matplotlib_dir]
        for path in candidates:
            if path == script_path or path.is_symlink() or not path.is_file():
                continue
            if len(artifacts) >= self.max_files:
                raise ValueError("Sandbox produced too many artifacts")
            size = path.stat().st_size
            if size > self.max_artifact_bytes - total_bytes:
                raise ValueError("Sandbox artifacts exceed the configured total size limit")
            data = path.read_bytes()
            total_bytes += len(data)
            mime_type, _encoding = mimetypes.guess_type(path.name)
            artifacts.append(
                Artifact(
                    data=data,
                    mime_type=mime_type or "application/octet-stream",
                    name=path.name,
                )
            )
        return artifacts


def _strip_markdown_code_fence(text: str) -> str:
    """Remove one surrounding Markdown code fence when a model adds it."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class DataScienceEngine:
    """Select one explicit backend and retain artifacts for A2A completion."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.artifact_store = FileArtifactStore(
            settings.artifacts_dir,
            max_file_bytes=settings.sandbox_max_artifact_bytes,
        )
        self.generated_artifacts: list[Artifact] = []
        self.resolved_mode = settings.sandbox_mode

        if settings.sandbox_mode is SandboxMode.CONTAINER:
            if shutil.which(settings.container_engine) is None:
                raise RuntimeError(
                    f"Required container engine {settings.container_engine!r} is unavailable"
                )
            container_config = ContainerConfig(
                image=settings.container_image,
                engine=settings.container_engine,
                timeout_s=settings.sandbox_timeout_s,
                memory_mb=settings.sandbox_memory_mb,
                cpus=settings.sandbox_cpus,
                pids_limit=settings.sandbox_pids_limit,
                workspace_mb=settings.sandbox_workspace_mb,
                max_code_bytes=settings.sandbox_max_code_bytes,
                max_output_bytes=settings.sandbox_max_output_bytes,
                max_artifact_bytes=settings.sandbox_max_artifact_bytes,
                max_files=settings.sandbox_max_files,
            )
            self.backend: ContainerPythonBackend | IsolatedSubprocessBackend = (
                ContainerPythonBackend(container_config)
            )
        else:
            self.backend = IsolatedSubprocessBackend(
                timeout_s=settings.sandbox_timeout_s,
                memory_limit_mb=settings.sandbox_memory_mb,
                max_code_bytes=settings.sandbox_max_code_bytes,
                max_output_bytes=settings.sandbox_max_output_bytes,
                max_artifact_bytes=settings.sandbox_max_artifact_bytes,
                max_files=settings.sandbox_max_files,
            )

    async def execute(self, code: str) -> InterpreterResult:
        """Execute code without weakening the selected confinement mode."""
        result = await self.backend.execute(_strip_markdown_code_fence(code))
        self.generated_artifacts.extend(result.files)
        return result

    async def environment_info(self) -> dict[str, object]:
        """Inspect packages inside the selected backend, not on the API host."""
        result = await self.execute(_ENVIRONMENT_PROBE)
        if result.exit_code != 0:
            raise RuntimeError("Sandbox environment inspection failed")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Sandbox returned invalid environment metadata") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Sandbox returned an invalid environment metadata object")
        return value

    async def run_code(self, code: str) -> tuple[InterpreterResult, list[dict[str, object]]]:
        """Execute code and persist references to every generated artifact."""
        result = await self.execute(code)
        references: list[dict[str, object]] = []
        for artifact in result.files:
            reference = self.artifact_store.put(artifact)
            references.append(
                {
                    "artifact_id": reference.artifact_id,
                    "mime_type": reference.mime_type,
                    "name": reference.name,
                    "sha256": reference.sha256,
                    "size_bytes": reference.size,
                }
            )
        return result, references
