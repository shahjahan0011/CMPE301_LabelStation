import sqlite3
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS production_orders (
            order_id INTEGER PRIMARY KEY,
            product_name TEXT,
            planned_quantity INTEGER,
            planned_production_time REAL,
            ideal_cycle_time REAL,
            status TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS oee_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER,
            runtime REAL,
            total_count INTEGER,
            good_count INTEGER,
            availability REAL,
            performance REAL,
            quality REAL,
            oee REAL
        )
        """)


def get_active_order():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM production_orders WHERE status='active' LIMIT 1"
        )
        return cur.fetchone()


def get_all_orders():
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM production_orders")
        return cur.fetchall()


def activate_next_order():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT order_id FROM production_orders WHERE status='queued' LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE production_orders SET status='active' WHERE order_id=?",
                (row[0],)
            )


def complete_order(order_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE production_orders SET status='completed' WHERE order_id=?",
            (order_id,)
        )


def insert_oee(record):
    with get_conn() as conn:
        conn.execute("""
        INSERT INTO oee_records
        (order_id, runtime, total_count, good_count,
         availability, performance, quality, oee)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.order_id,
            record.runtime,
            record.total_count,
            record.good_count,
            record.availability,
            record.performance,
            record.quality,
            record.oee
        ))