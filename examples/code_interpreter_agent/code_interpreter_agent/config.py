"""Validated settings for the sandboxed Code Interpreter Agent."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lughus import BaseSettings

__all__ = ["SandboxMode", "Settings"]


class SandboxMode(StrEnum):
    """Supported execution modes.

    ``SUBPROCESS`` is intentionally limited to local development and tests. It
    is process-isolated, but it is not a security boundary against hostile code.
    """

    CONTAINER = "container"
    SUBPROCESS = "subprocess"


_PINNED_IMAGE_RE = re.compile(r"[A-Za-z0-9./:_-]+@sha256:[a-f0-9]{64}")
_PROJECT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _sandbox_mode() -> SandboxMode:
    raw = _env("SANDBOX_MODE", SandboxMode.CONTAINER.value).lower()
    try:
        return SandboxMode(raw)
    except ValueError as exc:
        choices = ", ".join(mode.value for mode in SandboxMode)
        raise ValueError(f"SANDBOX_MODE must be one of: {choices}") from exc


def _artifacts_dir() -> Path:
    configured = _env("ARTIFACTS_DIR")
    return Path(configured).expanduser().resolve() if configured else _PROJECT_DIR / "artifacts"


@dataclass(frozen=True)
class Settings(BaseSettings):
    """Configuration for fail-closed Python execution and artifact export."""

    port: int = field(default_factory=lambda: _env_int("PORT", 8082))
    agent_name: str = "code_interpreter_agent"
    agent_description: str = (
        "Sandboxed data-science agent executing Python in a network-isolated OCI container "
        "and returning generated charts, tables, and workbooks."
    )

    sandbox_mode: SandboxMode = field(default_factory=_sandbox_mode)
    container_engine: str = field(default_factory=lambda: _env("CONTAINER_ENGINE", "docker"))
    container_image: str = field(default_factory=lambda: _env("CONTAINER_IMAGE"))
    sandbox_timeout_s: float = field(default_factory=lambda: _env_float("SANDBOX_TIMEOUT_S", 45.0))
    tool_timeout: float = field(default_factory=lambda: _env_float("TOOL_TIMEOUT", 60.0))
    sandbox_memory_mb: int = field(default_factory=lambda: _env_int("SANDBOX_MEMORY_MB", 512))
    sandbox_cpus: float = field(default_factory=lambda: _env_float("SANDBOX_CPUS", 1.0))
    sandbox_pids_limit: int = field(default_factory=lambda: _env_int("SANDBOX_PIDS_LIMIT", 64))
    sandbox_workspace_mb: int = field(default_factory=lambda: _env_int("SANDBOX_WORKSPACE_MB", 64))
    sandbox_max_code_bytes: int = field(
        default_factory=lambda: _env_int("SANDBOX_MAX_CODE_BYTES", 100_000)
    )
    sandbox_max_output_bytes: int = field(
        default_factory=lambda: _env_int("SANDBOX_MAX_OUTPUT_BYTES", 32_000)
    )
    sandbox_max_artifact_bytes: int = field(
        default_factory=lambda: _env_int("SANDBOX_MAX_ARTIFACT_BYTES", 10_000_000)
    )
    sandbox_max_files: int = field(default_factory=lambda: _env_int("SANDBOX_MAX_FILES", 10))
    max_context_tokens: int = field(default_factory=lambda: _env_int("MAX_CONTEXT_TOKENS", 12_000))
    max_attachment_chars: int = field(
        default_factory=lambda: _env_int("MAX_ATTACHMENT_CHARS", 20_000)
    )
    artifacts_dir: Path = field(default_factory=_artifacts_dir)

    def __post_init__(self) -> None:
        super().__post_init__()
        try:
            mode = SandboxMode(self.sandbox_mode)
        except ValueError as exc:
            raise ValueError("Unsupported sandbox mode") from exc
        object.__setattr__(self, "sandbox_mode", mode)

        positive = {
            "SANDBOX_TIMEOUT_S": self.sandbox_timeout_s,
            "SANDBOX_MEMORY_MB": self.sandbox_memory_mb,
            "SANDBOX_CPUS": self.sandbox_cpus,
            "SANDBOX_PIDS_LIMIT": self.sandbox_pids_limit,
            "SANDBOX_WORKSPACE_MB": self.sandbox_workspace_mb,
            "SANDBOX_MAX_CODE_BYTES": self.sandbox_max_code_bytes,
            "SANDBOX_MAX_OUTPUT_BYTES": self.sandbox_max_output_bytes,
            "SANDBOX_MAX_ARTIFACT_BYTES": self.sandbox_max_artifact_bytes,
            "SANDBOX_MAX_FILES": self.sandbox_max_files,
            "MAX_CONTEXT_TOKENS": self.max_context_tokens,
            "MAX_ATTACHMENT_CHARS": self.max_attachment_chars,
        }
        invalid = sorted(name for name, value in positive.items() if value <= 0)
        if invalid:
            raise ValueError(f"Settings must be positive: {', '.join(invalid)}")
        if self.tool_timeout < self.sandbox_timeout_s:
            raise ValueError("TOOL_TIMEOUT must be at least SANDBOX_TIMEOUT_S")
        if self.sandbox_max_files > self.max_artifacts:
            raise ValueError("SANDBOX_MAX_FILES cannot exceed MAX_ARTIFACTS")
        if self.sandbox_max_artifact_bytes > self.max_total_artifact_bytes:
            raise ValueError("SANDBOX_MAX_ARTIFACT_BYTES cannot exceed MAX_TOTAL_ARTIFACT_BYTES")

        if mode is SandboxMode.CONTAINER:
            if self.container_engine not in {"docker", "podman"}:
                raise ValueError("CONTAINER_ENGINE must be docker or podman")
            if not _PINNED_IMAGE_RE.fullmatch(self.container_image):
                raise ValueError(
                    "CONTAINER_IMAGE must be explicitly pinned as name@sha256:<64 hex chars>"
                )
        elif self.environment.strip().lower() == "production":
            raise ValueError("SANDBOX_MODE=subprocess is forbidden in production")
