"""BaseSettings must see .env values for EVERY field, including the first.

Regression: ``model`` (plain os.getenv) was evaluated before the dotenv file
was loaded — the load only happened as a side effect of later ``_env_*``
helpers — so AGENT_MODEL from .env was silently missed.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture()
def fresh_settings(tmp_path: Path, monkeypatch):
    """Import lughus.infra.config from scratch with a .env in tmp cwd."""
    (tmp_path / ".env").write_text("AGENT_MODEL=openai/gpt-4o-test\nHOST=127.0.0.9\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    # Reset the module-level dotenv flag so the fixture's .env is re-read.
    sys.modules.pop("lughus.infra.config", None)
    mod = importlib.import_module("lughus.infra.config")
    importlib.reload(mod)
    yield mod


def test_model_field_sees_dotenv_without_prior_env_lookup(fresh_settings) -> None:
    """The FIRST field factory must trigger the dotenv load itself."""
    settings = fresh_settings.BaseSettings()
    assert settings.model == "openai/gpt-4o-test"
    assert settings.host == "127.0.0.9"


def test_plain_getenv_fields_route_through_getenv_helper(fresh_settings) -> None:
    """Every string field must go through _getenv, not raw os.getenv."""
    src = Path(fresh_settings.__file__).read_text()
    body = src[src.index("class BaseSettings") :]
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(
            (
                "model:",
                "host:",
                "public_url:",
                "log_level:",
                "environment:",
                "api_bearer_token:",
                "cors_origins:",
            )
        ):
            assert "_getenv(" in stripped, f"raw os.getenv in field: {stripped}"
