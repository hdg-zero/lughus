> [← Documentation index](../index.md)

# Confined Python Execution & Sandboxing Security

Lughus enforces a **fail-closed** security model for executing agent-generated Python code. There is no implicit or unconfined `eval` or host-level execution fallback.

Code execution is governed through the canonical `code_interpreter` tool, requiring an explicit `PythonBackend` and `BinaryArtifactStore`.

```python
from lughus import (
    ContainerConfig,
    ContainerPythonBackend,
    FileArtifactStore,
    ToolRegistry,
    register_code_interpreter,
)

registry = ToolRegistry()
backend = ContainerPythonBackend(
    ContainerConfig(
        image="python:3.12-slim@sha256:4b4c730e160a28f4d80a1c6a2e8cfa10bf23bc7155e8ccbe0ffc4c23f2f5abde",
        engine="docker",  # or "podman"
        timeout_s=30.0,
        memory_mb=512,
        cpus=1.0,
    )
)
artifact_store = FileArtifactStore("/srv/agent-artifacts")

register_code_interpreter(
    registry,
    backend=backend,
    artifact_store=artifact_store,
    requires_approval=True,
)
```

---

## 1. OCI Container Confinement (`ContainerPythonBackend`)

When configured with `ContainerPythonBackend`, the host runtime constructs a hardened Docker or Podman invocation with defense-in-depth confinement flags:

| Mechanism | Flag / Setting | Security Guarantee |
|---|---|---|
| **Network Isolation** | `--network=none` | Kernel network namespace is completely unmapped. Outbound data exfiltration or inbound connections are physically impossible. |
| **Filesystem Immutability** | `--read-only` | Root container filesystem is mounted read-only. Host volumes are never mounted (`--volume` forbidden). |
| **Ephemeral Scratch Space** | `--tmpfs /workspace:...` | Single in-memory workspace for code execution, erased immediately upon container destruction. |
| **Privilege Elimination** | `--user=65534:65534` | Execution runs under unprivileged `nobody` UID/GID. |
| **Capability Dropping** | `--cap-drop=ALL` | Drops all Linux kernel capabilities (`CAP_NET_RAW`, `CAP_SYS_ADMIN`, `CAP_CHROOT`, etc.). |
| **No Privilege Escalation**| `--security-opt=no-new-privileges` | Prevents setuid binaries or sub-processes from acquiring elevated permissions. |
| **Memory Ceiling** | `--memory=<N>m` | Hard cgroup v2 RAM limit. Memory exhaustion triggers the kernel OOM killer rather than host degradation. |
| **CPU Quota** | `--cpus=<N>` | CPU core allocation quota prevents thread starvation of host processes. |
| **PID Limit** | `--pids-limit=64` | Protection against fork bombs and process exhaustion. |
| **Pull Disabled** | `--pull=never` | Prevents dynamic or unauthorized network image pulls during tool dispatch. |

---

## 2. Immutable Digest Requirement

To prevent supply-chain tampering and poisoned mutable image tags (e.g. `:latest` or `:3.12`), `ContainerConfig` strictly validates that images are pinned by their immutable SHA-256 digest:

```python
# Valid: Image pinned by cryptographic digest
config = ContainerConfig(
    image="python:3.12-slim@sha256:4b4c730e160a28f4d80a1c6a2e8cfa10bf23bc7155e8ccbe0ffc4c23f2f5abde"
)

# Invalid: Raises ValueError at registration
config = ContainerConfig(image="python:3.12-slim")
```

The operator must pre-pull and verify the container image on the worker nodes during deployment provisioning.

---

## 3. Artifact Security & Path Traversal Prevention

When the sandboxed script generates files (e.g. Matplotlib figures, Pandas CSV exports, Excel sheets), the execution driver gathers produced artifacts:

1. **Path Traversal Mitigation:** Artifact paths are strictly validated. Any relative path containing `..` or leading `/` is rejected immediately with a `ValueError`.
2. **Quota Bounds:** File count (`max_files`) and aggregate size (`max_artifact_bytes`) limits are enforced before reading binary payloads from `/workspace`.
3. **Decoupled Persistence:** Binary data is persisted to `FileArtifactStore` using random UUID-based identifiers (`artifact_id`) and forced disk sync (`fsync`), preventing model-controlled overwrite of host paths.

---

## 4. Pluggable Backends (`PythonBackend` Protocol)

For local development or offline integration tests where Docker or Podman is not available, the application can supply a custom backend conforming to the `PythonBackend` protocol:

```python
from lughus.engine.interpreter import InterpreterResult, PythonBackend


class LocalDevBackend:
    async def execute(self, code: str) -> InterpreterResult:
        # Run in isolated subprocess with RLIMIT bounds and socket restrictions
        ...
        return InterpreterResult(
            stdout="...",
            stderr="",
            exit_code=0,
            files=(),
            truncated=False,
        )
```

> **Note on Adversarial Multi-Tenancy:**  
> Container isolation relies on shared Linux kernels. For untrusted, adversarial multi-tenant workloads, run agent workers inside dedicated ephemeral virtual machines or microVMs (e.g., Firecracker / gVisor) behind the `PythonBackend` protocol.

---

**Related:** [Sandboxed Execution Guide](../guides/sandboxed-execution.md) · [Tools API](../api/tools.md) · [Threat Model](threat-model.md)
