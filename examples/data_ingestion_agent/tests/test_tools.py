"""Unit tests for Data Ingestion Agent tools and security policies."""

from __future__ import annotations

import json

import pytest
from data_ingestion_agent.database import init_demo_database
from data_ingestion_agent.tools import (
    describe_table,
    list_tables,
    query_database,
    registry,
    sample_table,
)

from lughus import SafeToolError, ToolEffect, ToolRisk


@pytest.fixture(autouse=True)
def setup_database(tmp_path, monkeypatch):
    """Ensure a fresh initialized database for tests."""
    db_path = tmp_path / "test_data.db"
    init_demo_database(db_path)
    monkeypatch.setattr("data_ingestion_agent.tools.DEFAULT_DB_PATH", db_path)


def test_tool_declarations_and_metadata():
    """Verify that tools have correct metadata and Least Privilege policies."""
    assert "list_tables" in registry
    assert "describe_table" in registry
    assert "sample_table" in registry
    assert "query_database" in registry

    for name in ("list_tables", "describe_table", "sample_table", "query_database"):
        tool_def = registry.get_tool(name)
        assert tool_def is not None
        assert tool_def.risk == ToolRisk.LOW
        assert tool_def.effects == frozenset([ToolEffect.READ])


def test_list_tables():
    raw = list_tables()
    data = json.loads(raw)
    assert "tables" in data
    table_names = {t["table_name"] for t in data["tables"]}
    assert {"orders", "customers", "warehouses", "fulfillment_delays"}.issubset(table_names)


def test_describe_table():
    raw = describe_table("orders")
    data = json.loads(raw)
    assert data["table_name"] == "orders"
    col_names = [c["column_name"] for c in data["columns"]]
    assert "order_id" in col_names
    assert "amount_eur" in col_names


def test_describe_table_unknown():
    with pytest.raises(SafeToolError) as exc_info:
        describe_table("non_existent_table")
    assert exc_info.value.code == "TABLE_NOT_FOUND"


def test_sample_table():
    raw = sample_table("warehouses", limit=3)
    data = json.loads(raw)
    assert data["table_name"] == "warehouses"
    assert len(data["rows"]) <= 3
    assert "warehouse_code" in data["rows"][0]


def test_sample_table_invalid_identifier():
    with pytest.raises(SafeToolError) as exc_info:
        sample_table("orders; DROP TABLE orders;--")
    assert exc_info.value.code == "INVALID_IDENTIFIER"


def test_query_database_success():
    raw = query_database("SELECT warehouse_code, city FROM warehouses ORDER BY city LIMIT 2")
    data = json.loads(raw)
    assert data["row_count"] == 2
    assert data["columns"] == ["warehouse_code", "city"]
    assert len(data["rows"]) == 2


def test_query_database_rejects_mutation():
    with pytest.raises(SafeToolError) as exc_info:
        query_database("DROP TABLE orders")
    assert exc_info.value.code in ("READ_ONLY_VIOLATION", "FORBIDDEN_OPERATION")

    with pytest.raises(SafeToolError) as exc_info:
        query_database("DELETE FROM orders WHERE order_id = 'ORD-1'")
    assert exc_info.value.code in ("READ_ONLY_VIOLATION", "FORBIDDEN_OPERATION")


def test_query_database_rejects_multi_statement():
    with pytest.raises(SafeToolError) as exc_info:
        query_database("SELECT 1; SELECT 2;")
    assert exc_info.value.code == "MULTI_STATEMENT_REJECTED"


def test_query_database_scrubs_syntax_error():
    # Verify that raw SQLite errors are masked by SafeToolError
    with pytest.raises(SafeToolError) as exc_info:
        query_database("SELECT non_existent_column FROM orders")
    assert exc_info.value.code == "SQL_SYNTAX_OR_EXECUTION_ERROR"
    # Ensure error message does not expose internal stack or file paths
    assert "Please verify column names" in str(exc_info.value)


def test_query_database_strips_markdown_code_fence():
    """Verify that queries wrapped in markdown ```sql ... ``` are cleanly processed."""
    wrapped_query = """```sql
SELECT warehouse_code, city FROM warehouses ORDER BY city LIMIT 1;
```"""
    raw = query_database(wrapped_query)
    data = json.loads(raw)
    assert data["row_count"] == 1
    assert data["columns"] == ["warehouse_code", "city"]
