"""Database manager and synthetic data generator for the Data Ingestion Agent.

Creates a realistic on-premise SQLite database containing supply chain and order
fulfillment data with embedded Q3 anomalies for educational data science analysis.
"""

from __future__ import annotations

import datetime
import random
import sqlite3
from pathlib import Path

__all__ = ["DEFAULT_DB_PATH", "init_demo_database"]

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "logistics_bi.db"


def init_demo_database(db_path: Path | str = DEFAULT_DB_PATH) -> Path:
    """Initialize the SQLite database with realistic business tables if not present."""
    target_path = Path(db_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and target_path.stat().st_size > 0:
        return target_path

    # Use a fixed seed for reproducible educational demonstrations
    rng = random.Random(42)

    conn = sqlite3.connect(target_path)
    try:
        cur = conn.cursor()

        # 1. Warehouses
        cur.execute(
            """
            CREATE TABLE warehouses (
                warehouse_code TEXT PRIMARY KEY,
                city TEXT NOT NULL,
                country TEXT NOT NULL,
                capacity_utilization_pct REAL NOT NULL,
                is_automated INTEGER NOT NULL
            )
            """
        )
        warehouses_data = [
            ("WH-LYON", "Lyon", "France", 88.5, 1),
            ("WH-PARIS", "Paris", "France", 94.2, 1),
            ("WH-LILLE", "Lille", "France", 73.0, 0),
            ("WH-MARSEILLE", "Marseille", "France", 82.4, 0),
            ("WH-BORDEAUX", "Bordeaux", "France", 68.9, 0),
        ]
        cur.executemany(
            "INSERT INTO warehouses VALUES (?, ?, ?, ?, ?)",
            warehouses_data,
        )

        # 2. Customers
        cur.execute(
            """
            CREATE TABLE customers (
                customer_id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                tier TEXT NOT NULL,
                region TEXT NOT NULL
            )
            """
        )
        customers_data = [
            (
                f"CUST-{i:03d}",
                f"Entreprise {chr(65 + (i % 26))}{i}",
                rng.choice(["Enterprise", "Mid-Market", "SMB"]),
                rng.choice(["Nord", "Sud", "Est", "Ouest", "IDF"]),
            )
            for i in range(1, 31)
        ]
        cur.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", customers_data)

        # 3. Orders & Fulfillment Delays
        cur.execute(
            """
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                customer_id TEXT NOT NULL,
                warehouse_code TEXT NOT NULL,
                order_date TEXT NOT NULL,
                amount_eur REAL NOT NULL,
                priority TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers (customer_id),
                FOREIGN KEY (warehouse_code) REFERENCES warehouses (warehouse_code)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE fulfillment_delays (
                order_id TEXT PRIMARY KEY,
                promised_date TEXT NOT NULL,
                actual_delivery_date TEXT NOT NULL,
                delay_days INTEGER NOT NULL,
                delay_category TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (order_id)
            )
            """
        )

        orders = []
        delays = []
        base_date = datetime.date(2026, 1, 1)

        for order_idx in range(1, 201):
            order_id = f"ORD-2026-{order_idx:04d}"
            customer_id = rng.choice(customers_data)[0]
            warehouse_code = rng.choice(warehouses_data)[0]

            # Spread over 9 months (Jan to Sept 2026)
            days_offset = rng.randint(0, 260)
            order_date = base_date + datetime.timedelta(days=days_offset)
            order_date_str = order_date.isoformat()

            amount = round(rng.uniform(150.0, 12500.0), 2)
            priority = rng.choice(["Standard", "Express", "Critical"])

            orders.append((order_id, customer_id, warehouse_code, order_date_str, amount, priority))

            # Delivery logic: simulate significant delay spike in Q3 (July - Sept: month 7, 8, 9)
            is_q3 = order_date.month in (7, 8, 9)
            promised_date = order_date + datetime.timedelta(days=2 if priority == "Express" else 5)

            if is_q3 and warehouse_code == "WH-PARIS":
                # Significant congestion delay
                delay_days = rng.randint(4, 14)
                category = "Warehouse Overload"
            elif is_q3 and rng.random() < 0.35:
                delay_days = rng.randint(2, 7)
                category = rng.choice(["Carrier Strike", "Customs Inspection"])
            elif rng.random() < 0.12:
                delay_days = rng.randint(1, 4)
                category = rng.choice(["Weather", "Warehouse Overload"])
            else:
                delay_days = 0
                category = "None"

            actual_delivery_date = promised_date + datetime.timedelta(days=delay_days)
            delays.append(
                (
                    order_id,
                    promised_date.isoformat(),
                    actual_delivery_date.isoformat(),
                    delay_days,
                    category,
                )
            )

        cur.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", orders)
        cur.executemany("INSERT INTO fulfillment_delays VALUES (?, ?, ?, ?, ?)", delays)

        conn.commit()
    finally:
        conn.close()

    return target_path
