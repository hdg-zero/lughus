"""Configuration settings for Data Ingestion Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from lughus import BaseSettings
from lughus.infra.config import _env_bool, _env_int

from .database import DEFAULT_DB_PATH

__all__ = ["Settings"]


def _database_path() -> Path:
    env_path = os.getenv("DATABASE_PATH")
    return Path(env_path).resolve() if env_path else DEFAULT_DB_PATH


@dataclass(frozen=True)
class Settings(BaseSettings):
    """Application and network settings for the Data Ingestion Agent."""

    port: int = field(default_factory=lambda: _env_int("PORT", 8081))
    enable_console: bool = field(default_factory=lambda: _env_bool("ENABLE_CONSOLE", True))
    agent_name: str = "data_ingestion_agent"
    agent_description: str = (
        "Specialist agent for secure local database schema inspection, data profiling, "
        "and read-only analytical query execution without information leakage."
    )
    database_path: Path = field(default_factory=_database_path)
