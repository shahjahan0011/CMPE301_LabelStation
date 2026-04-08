from repository import init_db
import sqlite3

init_db()

conn = sqlite3.connect("mes.db")

orders = [
    (101, "Label_A", 1, 20, 1.0, "active"),
    (102, "Label_B", 1, 20, 1.0, "queued"),
    (103, "Label_C", 1, 20, 1.0, "queued"),
]

conn.executemany("""
INSERT OR REPLACE INTO production_orders
VALUES (?, ?, ?, ?, ?, ?)
""", orders)

conn.commit()
conn.close()

print("Seeded DB.")