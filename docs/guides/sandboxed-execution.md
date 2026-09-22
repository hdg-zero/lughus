> [← Documentation index](../index.md)

# Sandboxed Python Execution Guide

This guide explains how to configure, govern, and execute untrusted agent-generated Python code within `lughus` using fail-closed sandboxing.

---

## 🎯 Why Sandboxed Execution?

When an AI agent acts as a Data Scientist or Code Interpreter, it generates executable Python code to run calculations, process DataFrames (Pandas, Polars), and render visual charts (Matplotlib, Seaborn).

Allowing an LLM to execute dynamic code on host infrastructure introduces critical risks:
- **Exfiltration:** Malicious or hallucinated network requests accessing external endpoints or cloud metadata APIs (`169.254.169.254`).
- **Filesystem Tampering:** Modification or reading of host files, environment variables, or secrets.
- **Resource Starvation:** Memory leaks, CPU loops, and fork bombs impacting co-located workloads.

Lughus solves this with a **fail-closed container execution architecture** and the canonical `code_interpreter` tool.

---

## 🏛️ Architecture & Component Model

The code execution pipeline decouples tool governance from the physical confinement engine:

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent Loop / LLM                       │
└──────────────────────────────┬──────────────────────────────┘
                               │ Invocations: code_interpreter(code)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   ToolRegistry & Policies                   │
│   ToolRisk.HIGH, ToolEffect.WRITE | ToolEffect.EXTERNAL     │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   PythonBackend Protocol                    │
│      async def execute(code: str) -> InterpreterResult      │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────────┐┌─────────────────────────────┐
│    ContainerPythonBackend    ││   IsolatedSubprocessBackend │
│ (Production: Docker/Podman)  ││   (Local Dev / Offline Test)│
└──────────────┬───────────────┘└─────────────┬───────────────┘
               │                              │
               └──────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              BinaryArtifactStore (FileArtifactStore)        │
│   Persists generated plots (.png), sheets (.xlsx), data     │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Setup: Production OCI Confinement

### 1. Provision the Pinned Container Image

In production, Lughus requires container images to be pinned by an immutable SHA-256 digest (tag names like `:latest` are strictly rejected). Pre-pull the image on your host:

```bash
docker pull python:3.12-slim@sha256:4b4c730e160a28f4d80a1c6a2e8cfa10bf23bc7155e8ccbe0ffc4c23f2f5abde
```

### 2. Configure and Register the Tool

```python
from lughus import (
    ContainerConfig,
    ContainerPythonBackend,
    FileArtifactStore,
    ToolRegistry,
    register_code_interpreter,
)

# 1. Initialize registry and artifact store
registry = ToolRegistry()
artifact_store = FileArtifactStore("./artifacts")

# 2. Configure OCI container parameters
config = ContainerConfig(
    image="python:3.12-slim@sha256:4b4c730e160a28f4d80a1c6a2e8cfa10bf23bc7155e8ccbe0ffc4c23f2f5abde",
    engine="docker",  # or "podman"
    timeout_s=30.0,
    memory_mb=512,
    cpus=1.0,
    pids_limit=64,
)

# 3. Instantiate backend and register canonical tool
backend = ContainerPythonBackend(config)
register_code_interpreter(
    registry,
    backend=backend,
    artifact_store=artifact_store,
    requires_approval=True,  # Enforce human-in-the-loop for high-risk execution
)
```

---

## 📊 Binary Artifact Handling

When executed Python code writes files into the working directory (e.g. `plt.savefig("chart.png")` or `df.to_csv("summary.csv")`), Lughus automatically:
1. Detects newly created files inside the ephemeral workspace.
2. Validates paths against traversal attempts (`..` or `/`).
3. Stores the files into `BinaryArtifactStore`.
4. Returns strongly typed references with unique UUIDs (`artifact_id`), mime-types, and SHA-256 hashes to the agent loop.

### Example in Agent Prompts

Instruct your agent to write outputs to the current working directory:

```markdown
To generate charts:
- Always save figures to disk: `plt.savefig("chart.png", bbox_inches="tight", dpi=150)`
- Cleanly close the figure: `plt.close()`
- Files saved in the current directory are automatically collected and returned as artifacts.
```

---

## 🛠️ Local Development & Testing (Without Docker)

For local development or offline environments where Docker/Podman is not installed, implement the `PythonBackend` protocol:

```python
import asyncio
import os
import pathlib
import sys
import tempfile
from lughus import Artifact, InterpreterResult, PythonBackend


class LocalSubprocessBackend:
    """Lightweight development backend running python -I in a temp directory."""

    async def execute(self, code: str) -> InterpreterResult:
        with tempfile.TemporaryDirectory(prefix="lughus-dev-") as tmpdir:
            workdir = pathlib.Path(tmpdir)
            script = workdir / "script.py"
            script.write_text(code, encoding="utf-8")

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(script),
                cwd=str(workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            # Collect any artifacts written to workdir
            files = []
            for file_path in workdir.glob("*"):
                if file_path.is_file() and file_path.name != "script.py":
                    files.append(
                        Artifact(
                            data=file_path.read_bytes(),
                            name=file_path.name,
                            mime_type="application/octet-stream",
                        )
                    )

            return InterpreterResult(
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                files=tuple(files),
                truncated=False,
            )
```

Plug this backend directly into `register_code_interpreter(registry, backend=LocalSubprocessBackend(), artifact_store=artifact_store)`.

---

## 🔒 Confinement Comparison

| Feature | `ContainerPythonBackend` | Local Subprocess (`python -I`) |
|---|---|---|
| **Primary Use Case** | Production & Multi-tenant | Local Development & Offline CI |
| **Prerequisites** | Docker or Podman daemon | Python standard library |
| **Network Access** | Physically disabled (`--network=none`) | Cooperative socket blocking |
| **Host Filesystem** | Read-only (`--read-only`, no volumes) | Unconfined user filesystem |
| **Memory / CPU Ceilings** | Enforced by Linux cgroups | Optional POSIX `setrlimit` |
| **Fork Bomb Mitigation** | Hard `--pids-limit=64` | None by default |

---

**Related:** [Confined Python Security](../security/python-execution.md) · [Tools API](../api/tools.md) · [Tools Contract](../contracts/tools.md)
