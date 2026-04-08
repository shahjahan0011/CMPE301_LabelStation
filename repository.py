import sqlite3
from datetime import datetime
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS production_orders (
            order_id INTEGER PRIMARY KEY,
            product_name TEXT NOT NULL DEFAULT '',
            planned_quantity INTEGER NOT NULL DEFAULT 1,
            planned_production_time REAL NOT NULL DEFAULT 60.0,
            ideal_cycle_time REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'active',
            start_timestamp TEXT,
            end_timestamp TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS oee_records (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            runtime REAL NOT NULL,
            total_count INTEGER NOT NULL,
            good_count INTEGER NOT NULL,
            state TEXT NOT NULL,
            availability REAL NOT NULL,
            performance REAL NOT NULL,
            quality REAL NOT NULL,
            oee_value REAL NOT NULL,
            FOREIGN KEY(order_id) REFERENCES production_orders(order_id)
        )
        """)


def ensure_order_exists(order_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT order_id FROM production_orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()

        if row is None:
            conn.execute("""
                INSERT INTO production_orders (
                    order_id, product_name, planned_quantity,
                    planned_production_time, ideal_cycle_time,
                    status, start_timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id,
                f"Phone_{order_id}",
                1,
                60.0,
                1.0,
                "active",
                datetime.now().isoformat()
            ))


def get_order(order_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM production_orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()


def complete_order(order_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE production_orders
            SET status = 'completed',
                end_timestamp = ?
            WHERE order_id = ?
        """, (datetime.now().isoformat(), order_id))


def insert_oee_record(order_id, runtime, total_count, good_count, state,
                      availability, performance, quality, oee_value):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO oee_records (
                order_id, timestamp, runtime, total_count, good_count, state,
                availability, performance, quality, oee_value
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            datetime.now().isoformat(),
            runtime,
            total_count,
            good_count,
            state,
            availability,
            performance,
            quality,
            oee_value
        ))


def get_latest_oee_record(order_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM oee_records
            WHERE order_id = ?
            ORDER BY record_id DESC
            LIMIT 1
        """, (order_id,)).fetchone()