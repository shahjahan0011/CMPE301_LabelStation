import sqlite3
from datetime import datetime
from config import DB_PATH

USERS = {
    "operator": {"password": "operator123", "role": "operator"},
    "viewer":   {"password": "viewer123",   "role": "viewer"},
}

IDEAL_CYCLE_TIME_DEFAULT = 11.5  # seconds — one labelling sequence


def get_conn():
    # check_same_thread=False required because Flask routes and the background
    # thread both access the DB. SQLite handles this safely with WAL mode below.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode gives better concurrent read/write performance
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS production_orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL DEFAULT '',
            planned_quantity INTEGER NOT NULL DEFAULT 1,
            planned_production_time REAL NOT NULL DEFAULT 11.5,
            ideal_cycle_time REAL NOT NULL DEFAULT 11.5,
            status TEXT NOT NULL DEFAULT 'queued',
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


# ------------------------------------------------------------------
# Order queue management
# ------------------------------------------------------------------

def add_order_to_queue(product_name, planned_quantity, ideal_cycle_time=IDEAL_CYCLE_TIME_DEFAULT):
    """Add a new order to the queue.
    planned_production_time is auto-calculated from quantity × ideal_cycle_time.
    Returns the new order_id."""
    planned_production_time = planned_quantity * ideal_cycle_time
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO production_orders (
                product_name, planned_quantity,
                planned_production_time, ideal_cycle_time,
                status
            ) VALUES (?, ?, ?, ?, 'queued')
        """, (product_name, planned_quantity, planned_production_time, ideal_cycle_time))
        return cur.lastrowid


def get_queued_orders():
    """Return all orders currently in the queue (not yet started), oldest first."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM production_orders
            WHERE status = 'queued'
            ORDER BY order_id ASC
        """).fetchall()


def pop_next_order():
    """Mark the oldest queued order as active and return it."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM production_orders
            WHERE status = 'queued'
            ORDER BY order_id ASC
            LIMIT 1
        """).fetchone()

        if row:
            conn.execute("""
                UPDATE production_orders
                SET status = 'active', start_timestamp = ?
                WHERE order_id = ?
            """, (datetime.now().isoformat(), row["order_id"]))

        return row


def get_active_order():
    """Return the currently active order if one exists."""
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM production_orders
            WHERE status = 'active'
            ORDER BY order_id DESC
            LIMIT 1
        """).fetchone()


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
            SET status = 'completed', end_timestamp = ?
            WHERE order_id = ?
        """, (datetime.now().isoformat(), order_id))


# ------------------------------------------------------------------
# OEE records — only written at completion, not every poll
# ------------------------------------------------------------------

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
            oee_value,
        ))


def insert_order_summary(order_id, total_runtime, total_count, good_count,
                         availability, performance, quality, oee_value):
    """Write one final summary row when an order completes.
    INSERT OR IGNORE prevents duplicates if completion fires more than once."""
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
            oee_value,
        ))


def get_all_order_summaries():
    with get_conn() as conn:
        return conn.execute("""
            SELECT * FROM order_summary
            ORDER BY summary_id DESC
        """).fetchall()


def get_aggregate_totals():
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                          AS orders_completed,
                SUM(total_count)                  AS total_parts,
                SUM(good_count)                   AS total_good_parts,
                SUM(total_runtime)                AS total_runtime_seconds,
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
