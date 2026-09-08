#!/usr/bin/env bash
# Run in the repository on each stacked branch. Does not push or edit source.
set -euo pipefail
uv sync --all-extras --dev --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy lughus
uv run pytest tests/ --cov=lughus --cov-branch --cov-report=term-missing
uv build
printf '\nAlso run live OCI, A2A/MCP interoperability and application smoke tests.\n'
