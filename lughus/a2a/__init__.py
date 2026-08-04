"""Agent-to-Agent (A2A) protocol integration and gateway abstractions."""

from __future__ import annotations

from ..gateway import BaseGateway, _safe_filename, _validate_artifacts, _validate_objective

__all__ = [
    "BaseGateway",
    "_safe_filename",
    "_validate_artifacts",
    "_validate_objective",
]
