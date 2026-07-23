"""
database.py — SQLite connection, UUID schema, and migrations.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app.db_helpers import new_uuid, utc_now
from app.migrations.uuid_schema import ensure_uuid_schema, uses_uuid_schema

DB_PATH = Path(__file__).resolve().parent.parent / "attendance.db"

DEFAULT_LEVELS: tuple[tuple[int, str], ...] = (
    (100, "100 Level"),
    (200, "200 Level"),
    (300, "300 Level"),
    (400, "400 Level"),
    (500, "500 Level"),
)


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def seed_default_levels(conn: sqlite3.Connection, department_id: str) -> None:
    now = utc_now()
    for sort_order, name in DEFAULT_LEVELS:
        existing = conn.execute(
            "SELECT id FROM levels WHERE department_id = ? AND name = ? AND is_deleted = 0",
            (department_id, name),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """
            INSERT INTO levels
                (id, department_id, name, sort_order, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (new_uuid(), department_id, name, sort_order, now, now),
        )


def ensure_all_department_levels(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id FROM departments WHERE is_deleted = 0"
    ).fetchall()
    for row in rows:
        seed_default_levels(conn, row["id"])


def soft_delete(conn: sqlite3.Connection, table: str, record_id: str) -> bool:
    now = utc_now()
    cur = conn.execute(
        f"UPDATE {table} SET is_deleted = 1, updated_at = ? WHERE id = ? AND is_deleted = 0",
        (now, record_id),
    )
    return cur.rowcount > 0


def init_db() -> dict:
    conn = get_connection()
    result = {"uuid_migrated": False}
    try:
        migrated = ensure_uuid_schema(conn)
        result["uuid_migrated"] = migrated
        ensure_all_department_levels(conn)
        conn.commit()
    finally:
        conn.close()
    return result


if __name__ == "__main__":
    info = init_db()
    if info.get("uuid_migrated"):
        print("Migrated database to UUID primary keys.")
    else:
        print("Database schema OK (UUID).")
    print(f"Database at: {DB_PATH}")
