import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parent.parent / "attendance.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

print("=== TABLES ===")
for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    print(r[0])

for table in ["course_registrations", "courses", "attendance_logs"]:
    print(f"\n=== FK {table} ===")
    for r in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
        print(dict(r))

print("\n=== INSERT TEST ===")
conn.execute("PRAGMA foreign_keys = ON")
try:
    conn.execute(
        "INSERT INTO course_registrations (matric_no, course_id) VALUES (?, ?)",
        ("__test__", 1),
    )
    conn.rollback()
    print("OK")
except Exception as e:
    print("ERROR:", e)
