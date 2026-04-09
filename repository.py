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

        # Final summary record written once per completed order
        conn.execute("""
        CREATE TABLE IF NOT EXISTS order_summary (
            summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            completed_at TEXT NOT NULL,
            total_runtime REAL NOT NULL,
            total_count INTEGER NOT NULL,
            good_count INTEGER NOT NULL,
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


def insert_order_summary(order_id, total_runtime, total_count, good_count,
                         availability, performance, quality, oee_value):
    """Write one final summary row when an order completes.
    Uses INSERT OR IGNORE so re-triggers of the completion latch don't duplicate."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO order_summary (
                order_id, completed_at, total_runtime, total_count, good_count,
                availability, performance, quality, oee_value
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_id,
            datetime.now().isoformat(),
            total_runtime,
            total_count,
            good_count,
            availability,
            performance,
            quality,
            oee_value
        ))


def get_all_order_summaries():
    """Return all completed order summaries newest-first."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM order_summary
            ORDER BY summary_id DESC
        """).fetchall()


def get_aggregate_totals():
    """Aggregate metrics across all completed orders."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                    AS orders_completed,
                SUM(total_count)            AS total_parts,
                SUM(good_count)             AS total_good_parts,
                SUM(total_runtime)          AS total_runtime_seconds,
                ROUND(AVG(availability) * 100, 2) AS avg_availability,
                ROUND(AVG(performance)  * 100, 2) AS avg_performance,
                ROUND(AVG(quality)      * 100, 2) AS avg_quality,
                ROUND(AVG(oee_value)    * 100, 2) AS avg_oee
            FROM order_summary
        """).fetchone()
        return dict(row) if row else {}


def get_latest_oee_record(order_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM oee_records
            WHERE order_id = ?
            ORDER BY record_id DESC
            LIMIT 1
        """, (order_id,)).fetchone()
