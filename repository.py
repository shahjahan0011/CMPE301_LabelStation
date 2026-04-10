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
            order_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name            TEXT    NOT NULL DEFAULT '',
            planned_quantity        INTEGER NOT NULL DEFAULT 1,
            planned_production_time REAL    NOT NULL DEFAULT 3600.0,
            ideal_cycle_time        REAL    NOT NULL DEFAULT 60.0,
            label_text              TEXT    NOT NULL DEFAULT '',
            mode                    TEXT    NOT NULL DEFAULT 'manual',
            status                  TEXT    NOT NULL DEFAULT 'active',
            printed_count           INTEGER NOT NULL DEFAULT 0,
            start_timestamp         TEXT,
            end_timestamp           TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS oee_records (
            record_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id        INTEGER NOT NULL,
            timestamp       TEXT    NOT NULL,
            run_time        REAL    NOT NULL,
            last_cycle_time REAL    NOT NULL,
            total_count     INTEGER NOT NULL,
            good_count      INTEGER NOT NULL,
            station_state   TEXT    NOT NULL,
            availability    REAL    NOT NULL,
            performance     REAL    NOT NULL,
            quality         REAL    NOT NULL,
            oee_value       REAL    NOT NULL,
            FOREIGN KEY(order_id) REFERENCES production_orders(order_id)
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS print_log (
            log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   INTEGER,
            label_text TEXT    NOT NULL,
            timestamp  TEXT    NOT NULL,
            success    INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(order_id) REFERENCES production_orders(order_id)
        )
        """)


def create_order(product_name: str, planned_quantity: int,
                 planned_production_time: float, ideal_cycle_time: float,
                 label_text: str, mode: str) -> int:
    with get_conn() as conn:
        cursor = conn.execute("""
            INSERT INTO production_orders
                (product_name, planned_quantity, planned_production_time,
                 ideal_cycle_time, label_text, mode, status, start_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
        """, (product_name, planned_quantity, planned_production_time,
              ideal_cycle_time, label_text, mode, datetime.now().isoformat()))
        return cursor.lastrowid


def get_active_order():
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM production_orders
            WHERE status = 'active'
            ORDER BY order_id DESC LIMIT 1
        """).fetchone()


def get_order(order_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM production_orders WHERE order_id = ?", (order_id,)
        ).fetchone()


def get_all_orders(limit: int = 100):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM production_orders
            ORDER BY order_id DESC LIMIT ?
        """, (limit,)).fetchall()


def increment_printed_count(order_id: int) -> bool:
    """Increment printed_count. Returns True if order is now complete."""
    with get_conn() as conn:
        conn.execute("""
            UPDATE production_orders
            SET printed_count = printed_count + 1
            WHERE order_id = ?
        """, (order_id,))
        row = conn.execute(
            "SELECT printed_count, planned_quantity FROM production_orders WHERE order_id = ?",
            (order_id,)
        ).fetchone()
        if row and row["printed_count"] >= row["planned_quantity"]:
            conn.execute("""
                UPDATE production_orders
                SET status = 'completed', end_timestamp = ?
                WHERE order_id = ?
            """, (datetime.now().isoformat(), order_id))
            return True
    return False


def complete_order(order_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE production_orders
            SET status = 'completed', end_timestamp = ?
            WHERE order_id = ?
        """, (datetime.now().isoformat(), order_id))


def cancel_order(order_id: int):
    with get_conn() as conn:
        conn.execute("""
            UPDATE production_orders
            SET status = 'cancelled', end_timestamp = ?
            WHERE order_id = ?
        """, (datetime.now().isoformat(), order_id))


def insert_oee_record(order_id, run_time, last_cycle_time, total_count,
                      good_count, station_state, availability, performance,
                      quality, oee_value):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO oee_records
                (order_id, timestamp, run_time, last_cycle_time, total_count,
                 good_count, station_state, availability, performance, quality, oee_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (order_id, datetime.now().isoformat(), run_time, last_cycle_time,
              total_count, good_count, station_state, availability, performance,
              quality, oee_value))


def get_latest_oee(order_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM oee_records
            WHERE order_id = ?
            ORDER BY record_id DESC LIMIT 1
        """, (order_id,)).fetchone()


def get_oee_history(order_id: int, limit: int = 200):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM oee_records
            WHERE order_id = ?
            ORDER BY record_id ASC LIMIT ?
        """, (order_id, limit)).fetchall()


def log_print(order_id, label_text: str, success: bool):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO print_log (order_id, label_text, timestamp, success)
            VALUES (?, ?, ?, ?)
        """, (order_id, label_text, datetime.now().isoformat(), 1 if success else 0))


def get_print_log(order_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM print_log WHERE order_id = ?
            ORDER BY log_id DESC
        """, (order_id,)).fetchall()
