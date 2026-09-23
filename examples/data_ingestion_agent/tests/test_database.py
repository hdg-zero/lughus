"""Unit tests for the synthetic demo database generator."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from data_ingestion_agent.database import init_demo_database


def test_init_demo_database_creates_tables() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_bi.db"
        created_path = init_demo_database(db_path)
        assert created_path.exists()
        assert created_path.stat().st_size > 0

        conn = sqlite3.connect(created_path)
        cur = conn.cursor()

        # Verify all tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert {"warehouses", "customers", "orders", "fulfillment_delays"}.issubset(tables)

        # Verify row counts
        cur.execute("SELECT COUNT(*) FROM orders")
        orders_count = cur.fetchone()[0]
        assert orders_count == 200

        cur.execute("SELECT COUNT(*) FROM fulfillment_delays")
        delays_count = cur.fetchone()[0]
        assert delays_count == 200

        # Verify Q3 anomalies exist in the data
        cur.execute(
            """
            SELECT COUNT(*) FROM orders o
            JOIN fulfillment_delays d ON o.order_id = d.order_id
            WHERE o.order_date >= '2026-07-01' AND o.order_date <= '2026-09-30'
            AND d.delay_days > 0
            """
        )
        q3_delayed_orders = cur.fetchone()[0]
        assert q3_delayed_orders > 0

        conn.close()
