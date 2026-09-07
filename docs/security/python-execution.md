# Confined Python execution (0.20)

There is no local `run_python` fallback. Configure a `ContainerPythonBackend`
with an image pinned by digest, pre-pulled by the operator. Docker or Podman must
be available on a Linux worker with enforced cgroup limits.

```python
backend = ContainerPythonBackend(ContainerConfig(
    engine="podman", image="python@sha256:<your-verified-64-character-digest>",
))
register_code_interpreter(registry, backend=backend,
    artifact_store=FileArtifactStore("/srv/agent-artifacts"))
```

Defaults: non-root, no network, read-only root filesystem, no host mounts, no
capabilities, no-new-privileges, bounded CPU/memory/PIDs/workspace. No application
secrets are passed to the container. The host enforces a deadline and forcibly
removes the uniquely named container on cancellation or failure. Provision a
periodic `lughus-*` orphan-container reconciliation job for daemon/host failures.
The container runtime's default seccomp/LSM policy remains enabled; operators must
not disable it. Do not run the agent service itself as a privileged container.

This is process/container isolation, not a microVM or a kernel security proof.
For adversarial multi-tenancy, use dedicated hardened workers or a stronger
runtime behind the PythonBackend protocol. A compromised host daemon remains
outside the framework's trust boundary.

The container captures bounded output and exports bounded binary data. The host
validates the envelope, paths and total size, then the tool publishes bytes into
an application-owned BinaryArtifactStore. Returned references outlive the scratch
workspace. FileArtifactStore uses random IDs and fsync, not model-selected paths.
The embedding application must enforce artifact ACLs, retention and disk quotas.
Default tool approval remains enabled. Approving a tool does not approve further
outbound network access: the backend remains network-disabled.
