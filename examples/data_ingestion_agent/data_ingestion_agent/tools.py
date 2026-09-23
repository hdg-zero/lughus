"""Governed database inspection and querying tools.

Illustrates Lughus v0.22 Pydantic-first tool ergonomics, Least Privilege
policies (ToolEffect.READ, ToolRisk.LOW), and information leakage prevention
via SafeToolError redaction.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path

from lughus import (
    ConcurrencyMode,
    SafeToolError,
    ToolEffect,
    ToolRegistry,
    ToolRisk,
)

from .database import DEFAULT_DB_PATH, init_demo_database

__all__ = ["TOOL_NAMES", "create_tool_registry", "registry", "set_db_path"]

registry = ToolRegistry()

_override_db_path: Path | None = None


def set_db_path(path: Path | None) -> None:
    """Explicitly override database path for tests or custom environments."""
    global _override_db_path
    _override_db_path = path


def _get_db_path() -> Path:
    """Resolve database path with fallback to DATABASE_PATH env var and DEFAULT_DB_PATH."""
    if _override_db_path is not None:
        return _override_db_path
    env_path = os.getenv("DATABASE_PATH")
    if env_path:
        return Path(env_path).resolve()
    return DEFAULT_DB_PATH


def _strip_markdown_code_fence(text: str) -> str:
    """Strip markdown code fence wrappers (e.g. ```sql ... ```) if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _get_read_only_connection(db_path: Path) -> sqlite3.Connection:
    """Open an explicit read-only connection to SQLite using URI syntax."""
    # Ensure database is initialized before opening read-only URI
    if not db_path.exists():
        init_demo_database(db_path)
    uri = f"file:{db_path.resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


# Forbidden SQL statements that mutate or expose database internals
_FORBIDDEN_SQL_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|REPLACE)\b",
    re.IGNORECASE,
)


@registry.tool(
    name="list_tables",
    risk=ToolRisk.LOW,
    effects=frozenset([ToolEffect.READ]),
    concurrency=ConcurrencyMode.PARALLEL_SAFE,
    idempotent=True,
)
def list_tables() -> str:
    """List all available tables and their row counts in the local business database.

    Returns:
        JSON string containing the table names and respective row counts.
    """
    conn = _get_read_only_connection(_get_db_path())
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cur.fetchall()]

        results = []
        for tbl in tables:
            # Table name verified against sqlite_master
            cur.execute(f"SELECT COUNT(*) FROM [{tbl}]")
            count = cur.fetchone()[0]
            results.append({"table_name": tbl, "row_count": count})

        return json.dumps({"tables": results}, ensure_ascii=False)
    except sqlite3.Error as exc:
        # Prevent leaking file paths or internal connection errors
        raise SafeToolError(
            "METADATA_ERROR",
            "Unable to retrieve database table list.",
        ) from exc
    finally:
        conn.close()


@registry.tool(
    name="describe_table",
    risk=ToolRisk.LOW,
    effects=frozenset([ToolEffect.READ]),
    concurrency=ConcurrencyMode.PARALLEL_SAFE,
    idempotent=True,
)
def describe_table(table_name: str) -> str:
    """Inspect the schema, columns, and data types of a specific database table.

    Args:
        table_name: The exact name of the table to inspect (e.g. 'orders', 'fulfillment_delays').

    Returns:
        JSON string containing the column names, SQLite types, nullability, and primary key flags.
    """
    clean_name = table_name.strip()
    if not re.fullmatch(r"^[a-zA-Z0-9_]+$", clean_name):
        raise SafeToolError("INVALID_IDENTIFIER", "Table name contains invalid characters.")

    conn = _get_read_only_connection(_get_db_path())
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (clean_name,))
        if not cur.fetchone():
            raise SafeToolError("TABLE_NOT_FOUND", f"Table '{clean_name}' does not exist.")

        # Table exists in sqlite_master, safe to inspect with PRAGMA table_info
        cur.execute(f"PRAGMA table_info([{clean_name}])")
        columns = [
            {
                "cid": row[0],
                "column_name": row[1],
                "data_type": row[2],
                "not_null": bool(row[3]),
                "primary_key": bool(row[5]),
            }
            for row in cur.fetchall()
        ]
        return json.dumps({"table_name": clean_name, "columns": columns}, ensure_ascii=False)
    except SafeToolError:
        raise
    except sqlite3.Error as exc:
        raise SafeToolError(
            "SCHEMA_INSPECTION_FAILED",
            f"Failed to inspect schema for table '{clean_name}'.",
        ) from exc
    finally:
        conn.close()


@registry.tool(
    name="sample_table",
    risk=ToolRisk.LOW,
    effects=frozenset([ToolEffect.READ]),
    concurrency=ConcurrencyMode.PARALLEL_SAFE,
    idempotent=True,
)
def sample_table(table_name: str, limit: int = 5) -> str:
    """Fetch an exploratory sample of rows from a table to understand data values.

    Args:
        table_name: The table to sample from.
        limit: Maximum number of rows to return (default: 5, max: 20).

    Returns:
        JSON string containing column headers and sampled rows.
    """
    clean_name = table_name.strip()
    if not re.fullmatch(r"^[a-zA-Z0-9_]+$", clean_name):
        raise SafeToolError("INVALID_IDENTIFIER", "Table name contains invalid characters.")

    safe_limit = max(1, min(limit, 20))

    conn = _get_read_only_connection(_get_db_path())
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (clean_name,))
        if not cur.fetchone():
            raise SafeToolError("TABLE_NOT_FOUND", f"Table '{clean_name}' does not exist.")

        cur.execute(f"SELECT * FROM [{clean_name}] LIMIT ?", (safe_limit,))
        rows = [dict(row) for row in cur.fetchall()]
        return json.dumps(
            {"table_name": clean_name, "sample_size": len(rows), "rows": rows},
            ensure_ascii=False,
            default=str,
        )
    except SafeToolError:
        raise
    except sqlite3.Error as exc:
        raise SafeToolError(
            "SAMPLING_FAILED",
            f"Failed to sample data from table '{clean_name}'.",
        ) from exc
    finally:
        conn.close()


@registry.tool(
    name="query_database",
    risk=ToolRisk.LOW,
    effects=frozenset([ToolEffect.READ]),
    concurrency=ConcurrencyMode.PARALLEL_SAFE,
    idempotent=True,
)
def query_database(sql_query: str, max_rows: int = 100) -> str:
    """Execute a read-only SQL query against the database to extract analytical metrics.

    Args:
        sql_query: The SELECT or WITH query to execute. Mutative statements are strictly rejected.
        max_rows: Maximum rows to return (default: 100, max: 500).

    Returns:
        JSON string containing the column list, row count, and query results.
    """
    query = _strip_markdown_code_fence(sql_query)
    if not query:
        raise SafeToolError("EMPTY_QUERY", "The SQL query cannot be empty.")

    # Reject multi-statement queries
    if ";" in query.rstrip(";"):
        raise SafeToolError("MULTI_STATEMENT_REJECTED", "Only single SQL queries are permitted.")

    # Must start with SELECT or WITH
    if not (query.upper().startswith("SELECT") or query.upper().startswith("WITH")):
        raise SafeToolError(
            "READ_ONLY_VIOLATION",
            "Only read-only SELECT or WITH statements are allowed. "
            "PRAGMA or schema statements are prohibited in query_database. "
            "Use the dedicated tools 'describe_table' or 'list_tables' to inspect schemas.",
            retryable=True,
        )

    # Strictly disallow DDL / DML keywords
    if _FORBIDDEN_SQL_RE.search(query):
        raise SafeToolError(
            "FORBIDDEN_OPERATION",
            (
                "Query contains unauthorized keywords (mutations, administrative, "
                "PRAGMA or attachment statements). Only pure SELECT queries are permitted."
            ),
            retryable=True,
        )

    safe_max_rows = max(1, min(max_rows, 500))

    conn = _get_read_only_connection(_get_db_path())
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query)
        raw_rows = cur.fetchmany(safe_max_rows)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = [dict(row) for row in raw_rows]

        return json.dumps(
            {
                "columns": columns,
                "row_count": len(rows),
                "truncated": len(rows) >= safe_max_rows,
                "rows": rows,
            },
            ensure_ascii=False,
            default=str,
        )
    except SafeToolError:
        raise
    except sqlite3.Error as exc:
        # Crucial security feature: Redact raw SQL engine exception messages and file paths
        # so they do not leak table internals or assist prompt injection.
        raise SafeToolError(
            "SQL_SYNTAX_OR_EXECUTION_ERROR",
            (
                "The SQL query could not be executed. "
                "Please verify column names, aliases, and SQL syntax."
            ),
        ) from exc
    finally:
        conn.close()


TOOL_NAMES = ["list_tables", "describe_table", "sample_table", "query_database"]


def create_tool_registry() -> ToolRegistry:
    """Factory creating an isolated ToolRegistry instance with all tools."""
    return registry
