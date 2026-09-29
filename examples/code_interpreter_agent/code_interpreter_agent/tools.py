"""Governed tools backed by the selected Python sandbox."""

from __future__ import annotations

import json

from lughus import (
    ConcurrencyMode,
    ToolEffect,
    ToolRegistry,
    ToolRisk,
    register_code_interpreter,
)

from .config import Settings
from .engine import DataScienceEngine

__all__ = [
    "TOOL_NAMES",
    "create_tool_registry",
    "get_environment_info",
    "get_sandbox_info",
]

TOOL_NAMES = ("code_interpreter", "get_sandbox_info", "get_environment_info")


def get_sandbox_info(engine: DataScienceEngine, settings: Settings) -> str:
    """Return the effective confinement mode and resource ceilings."""
    container = engine.resolved_mode.value == "container"
    return json.dumps(
        {
            "container_engine": settings.container_engine if container else None,
            "container_image": settings.container_image if container else None,
            "cpus": settings.sandbox_cpus,
            "max_artifact_bytes": settings.sandbox_max_artifact_bytes,
            "max_files": settings.sandbox_max_files,
            "memory_mb": settings.sandbox_memory_mb,
            "network_access": False,
            "sandbox_mode": engine.resolved_mode.value,
            "timeout_s": settings.sandbox_timeout_s,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


async def get_environment_info(engine: DataScienceEngine) -> str:
    """Return package versions observed inside the selected sandbox."""
    info = await engine.environment_info()
    info["supported_export_formats"] = ["csv", "pdf", "png", "svg", "xlsx"]
    return json.dumps(info, ensure_ascii=False, sort_keys=True)


def create_tool_registry(
    engine: DataScienceEngine,
    settings: Settings,
    *,
    requires_approval: bool = False,
) -> ToolRegistry:
    """Create one request-scoped registry bound to ``engine``."""
    registry = ToolRegistry()
    register_code_interpreter(
        registry,
        backend=engine,
        artifact_store=engine.artifact_store,
        requires_approval=requires_approval,
    )

    @registry.tool(
        name="get_sandbox_info",
        risk=ToolRisk.LOW,
        effects=frozenset({ToolEffect.READ}),
        concurrency=ConcurrencyMode.PARALLEL_SAFE,
        idempotent=True,
    )
    def sandbox_info() -> str:
        """Inspect active sandbox isolation and resource limits."""
        return get_sandbox_info(engine, settings)

    @registry.tool(
        name="get_environment_info",
        risk=ToolRisk.LOW,
        effects=frozenset({ToolEffect.EXTERNAL, ToolEffect.READ}),
        concurrency=ConcurrencyMode.SERIAL_PER_TOOL,
        idempotent=True,
    )
    async def environment_info() -> str:
        """Inspect analytical packages from inside the sandbox."""
        return await get_environment_info(engine)

    return registry
