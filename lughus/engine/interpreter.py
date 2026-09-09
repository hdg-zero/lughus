"""Fail-closed Python execution inside an explicitly configured OCI container.

Docker/Podman is required. No subprocess-only fallback exists. Containers share
host kernels: use hardened, dedicated workers for adversarial multi-tenancy.
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from ..core.binary_artifacts import BinaryArtifactStore
from ..core.events import Artifact

if TYPE_CHECKING:
    from .tools import ToolRegistry

MAX_OUTPUT_CHARS = 20_000


class InterpreterTimeoutError(TimeoutError):
    """The host deadline expired; the container is forcibly removed."""


class SandboxUnavailableError(RuntimeError):
    """A required confinement backend is missing or failed."""


@dataclass(frozen=True, slots=True)
class ContainerConfig:
    image: str  # immutable image digest, explicitly chosen by the application
    engine: str = "docker"
    timeout_s: float = 30.0
    memory_mb: int = 256
    cpus: float = 1.0
    pids_limit: int = 64
    workspace_mb: int = 32
    max_code_bytes: int = 100_000
    max_output_bytes: int = 20_000
    max_artifact_bytes: int = 10_000_000
    max_files: int = 32

    def __post_init__(self) -> None:
        if self.engine not in {"docker", "podman"}:
            raise ValueError("Only docker and podman backends are supported")
        if not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}", self.image):
            raise ValueError("Pin the Python image with an immutable sha256 digest")
        if any(
            getattr(self, field) <= 0
            for field in (
                "timeout_s",
                "memory_mb",
                "cpus",
                "pids_limit",
                "workspace_mb",
                "max_code_bytes",
                "max_output_bytes",
                "max_artifact_bytes",
                "max_files",
            )
        ):
            raise ValueError("All sandbox limits must be positive")


@dataclass(frozen=True, slots=True)
class InterpreterResult:
    stdout: str
    stderr: str
    exit_code: int
    files: tuple[Artifact, ...] = ()
    truncated: bool = False


class PythonBackend(Protocol):
    async def execute(self, code: str) -> InterpreterResult: ...


_DRIVER = (
    "import base64, json, os, pathlib, selectors, subprocess, sys\n"
    "request = json.load(sys.stdin)\n"
    "os.chdir('/workspace')\n"
    "process = subprocess.Popen([sys.executable, '-I', '-c', request['code']],\n"
    "    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,\n"
    "    env={'PATH':'/usr/local/bin:/usr/bin:/bin', 'HOME':'/workspace', 'LANG':'C.UTF-8'})\n"
    "selector = selectors.DefaultSelector()\n"
    "selector.register(process.stdout, selectors.EVENT_READ, 'stdout')\n"
    "selector.register(process.stderr, selectors.EVENT_READ, 'stderr')\n"
    "streams = {'stdout': bytearray(), 'stderr': bytearray()}\n"
    "truncated = False\n"
    "while selector.get_map():\n"
    "    for key, _ in selector.select():\n"
    "        chunk = os.read(key.fileobj.fileno(), 8192)\n"
    "        if not chunk:\n"
    "            selector.unregister(key.fileobj)\n"
    "            continue\n"
    "        target = streams[key.data]\n"
    "        remaining = request['max_output_bytes'] - len(target)\n"
    "        target.extend(chunk[:max(remaining, 0)])\n"
    "        truncated = truncated or len(chunk) > remaining\n"
    "exit_code = process.wait()\n"
    "files = []\n"
    "total = 0\n"
    "for path in sorted(pathlib.Path('/workspace').rglob('*')):\n"
    "    if len(files) >= request['max_files']:\n"
    "        break\n"
    "    if path.is_symlink() or not path.is_file():\n"
    "        continue\n"
    "    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\n"
    "    with os.fdopen(fd, 'rb') as source:\n"
    "        data = source.read(request['max_artifact_bytes'] - total + 1)\n"
    "    total += len(data)\n"
    "    if total > request['max_artifact_bytes']:\n"
    "        raise ValueError('Artifact output exceeds limit')\n"
    "    files.append({'name':str(path.relative_to('/workspace')), "
    "'data':base64.b64encode(data).decode('ascii')})\n"
    "print(json.dumps({'stdout':streams['stdout'].decode('utf-8','replace'),\n"
    "    'stderr':streams['stderr'].decode('utf-8','replace'), 'exit_code':exit_code,\n"
    "    'truncated':truncated, 'files':files}))\n"
)


class ContainerPythonBackend:
    """Ephemeral non-root container, no network, no host mounts, no secrets.

    Provision the pinned image ahead of time: implicit pulls are forbidden.
    A local CLI and functioning daemon/rootless Podman are required. Limits rely
    on a correctly configured Linux container runtime and cgroup enforcement.
    """

    def __init__(self, config: ContainerConfig) -> None:
        self.config = config

    def command(self, name: str) -> list[str]:
        c = self.config
        engine = shutil.which(c.engine)
        if engine is None:
            raise SandboxUnavailableError(f"Required container engine {c.engine} is unavailable")
        return [
            engine,
            "run",
            "--interactive",
            "--name",
            name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            f"--memory={c.memory_mb}m",
            f"--memory-swap={c.memory_mb}m",
            f"--cpus={c.cpus}",
            f"--pids-limit={c.pids_limit}",
            "--ulimit=nofile=64:64",
            "--tmpfs",
            f"/workspace:rw,nosuid,nodev,noexec,size={c.workspace_mb}m,uid=65534,gid=65534,mode=700",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
            "--workdir=/workspace",
            "--entrypoint=python",
            c.image,
            "-I",
            "-c",
            _DRIVER,
        ]

    @staticmethod
    async def _read(stream: asyncio.StreamReader, limit: int) -> bytes:
        data = bytearray()
        while chunk := await stream.read(8192):
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("Sandbox output exceeds transport limit")
        return bytes(data)

    async def execute(self, code: str) -> InterpreterResult:
        c = self.config
        if len(code.encode()) > c.max_code_bytes:
            raise ValueError("Python code exceeds configured size limit")
        name = "lughus-" + uuid4().hex
        command = self.command(name)
        # Only local engine discovery context; never inherit application secrets.
        env = {"PATH": os.defpath, "HOME": str(Path.home())}
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            env["XDG_RUNTIME_DIR"] = runtime_dir
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        payload = json.dumps(
            {
                "code": code,
                "max_output_bytes": c.max_output_bytes,
                "max_artifact_bytes": c.max_artifact_bytes,
                "max_files": c.max_files,
            }
        ).encode()
        limit = c.max_artifact_bytes * 2 + c.max_output_bytes * 12 + c.max_files * 4096 + 4096
        readers: list[asyncio.Task[bytes]] = []
        try:
            async with asyncio.timeout(c.timeout_s):
                readers = [
                    asyncio.create_task(self._read(process.stdout, limit)),
                    asyncio.create_task(self._read(process.stderr, c.max_output_bytes)),
                ]
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
                output, _diagnostics = await asyncio.gather(*readers)
                await process.wait()
                if process.returncode != 0:
                    raise SandboxUnavailableError(
                        "Container execution failed; inspect the worker runtime"
                    )
                return self._decode(output)
        except TimeoutError as exc:
            raise InterpreterTimeoutError("Python execution exceeded its host deadline") from exc
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            if process.returncode is None:
                process.kill()
                await process.wait()
            # The CLI process is not the container. Kill the container by its unique
            # name even when cancellation or malformed output terminates the CLI.
            cleanup = asyncio.create_task(self._remove(command[0], name, env))
            await asyncio.shield(cleanup)

    @staticmethod
    async def _remove(engine: str, name: str, env: Mapping[str, str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            engine,
            "rm",
            "--force",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=dict(env),
        )
        try:
            await asyncio.wait_for(proc.wait(), 10.0)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise SandboxUnavailableError(
                "Container cleanup timed out; worker reconciliation required"
            ) from exc
        if proc.returncode != 0:
            raise SandboxUnavailableError(
                "Container removal failed; worker reconciliation required"
            )

    def _decode(self, output: bytes) -> InterpreterResult:
        c = self.config
        data = json.loads(output)
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            raise ValueError("Invalid sandbox result envelope")
        if len(data["files"]) > c.max_files or type(data.get("exit_code")) is not int:
            raise ValueError("Invalid sandbox result limits")
        files: list[Artifact] = []
        total = 0
        names: set[str] = set()
        for item in data["files"]:
            name = item["name"]
            if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
                raise ValueError("Invalid artifact name")
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or name in names:
                raise ValueError("Unsafe or duplicate artifact path")
            names.add(name)
            encoded = item["data"]
            if not isinstance(encoded, str) or len(encoded) > ((c.max_artifact_bytes + 2) // 3) * 4:
                raise ValueError("Artifact exceeds encoded limit")
            raw = base64.b64decode(encoded, validate=True)
            total += len(raw)
            if total > c.max_artifact_bytes:
                raise ValueError("Artifacts exceed total size limit")
            files.append(
                Artifact(raw, mimetypes.guess_type(name)[0] or "application/octet-stream", name)
            )
        stdout, stderr = data.get("stdout"), data.get("stderr")
        if not isinstance(stdout, str) or not isinstance(stderr, str):
            raise ValueError("Invalid sandbox streams")
        if len(stdout) > c.max_output_bytes or len(stderr) > c.max_output_bytes:
            raise ValueError("Sandbox stream exceeds limit")
        return InterpreterResult(
            stdout, stderr, data["exit_code"], tuple(files), bool(data.get("truncated"))
        )


def register_code_interpreter(
    registry: ToolRegistry,
    *,
    backend: PythonBackend,
    artifact_store: BinaryArtifactStore,
    requires_approval: bool = True,
) -> str:
    """Register an explicit confined backend and export files before workspace teardown."""
    from .tools import ToolEffect, ToolRisk

    @registry.tool(
        name="code_interpreter",
        risk=ToolRisk.HIGH,
        effects=frozenset({ToolEffect.WRITE, ToolEffect.EXTERNAL}),
        requires_approval=requires_approval,
    )
    async def code_interpreter(code: str) -> dict[str, Any]:
        result = await backend.execute(code)
        references = [
            asdict(await asyncio.to_thread(artifact_store.put, file)) for file in result.files
        ]
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "truncated": result.truncated,
            "files": references,
        }

    return "code_interpreter"
