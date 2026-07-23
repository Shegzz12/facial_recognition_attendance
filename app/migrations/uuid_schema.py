"""
UUID schema definition and migration from legacy integer-primary-key databases.
"""

from __future__ import annotations

import sqlite3

from app.db_helpers import new_uuid, utc_now

UUID_SCHEMA = """
CREATE TABLE IF NOT EXISTS departments (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    code            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_departments_code_active
    ON departments(code) WHERE code IS NOT NULL AND is_deleted = 0;

CREATE TABLE IF NOT EXISTS levels (
    id              TEXT PRIMARY KEY,
    department_id   TEXT NOT NULL REFERENCES departments(id),
    name            TEXT NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(department_id, name)
);

CREATE TABLE IF NOT EXISTS courses (
    id              TEXT PRIMARY KEY,
    department_id   TEXT NOT NULL REFERENCES departments(id),
    level_id        TEXT NOT NULL REFERENCES levels(id),
    code            TEXT NOT NULL,
    name            TEXT NOT NULL,
    lecturer        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(department_id, level_id, code)
);

CREATE TABLE IF NOT EXISTS students (
    id              TEXT PRIMARY KEY,
    matric_no       TEXT NOT NULL UNIQUE,
    full_name       TEXT NOT NULL,
    department_id   TEXT REFERENCES departments(id),
    level_id        TEXT REFERENCES levels(id),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS course_registrations (
    id              TEXT PRIMARY KEY,
    matric_no       TEXT NOT NULL REFERENCES students(matric_no),
    course_id       TEXT NOT NULL REFERENCES courses(id),
    registered_at   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(matric_no, course_id)
);

CREATE TABLE IF NOT EXISTS face_samples (
    id              TEXT PRIMARY KEY,
    matric_no       TEXT NOT NULL REFERENCES students(matric_no),
    image_path      TEXT NOT NULL,
    frame_index     INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    id              TEXT PRIMARY KEY,
    matric_no       TEXT NOT NULL REFERENCES students(matric_no),
    vector          BLOB NOT NULL,
    vector_dim      INTEGER NOT NULL,
    source_frame    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS attendance_logs (
    id              TEXT PRIMARY KEY,
    matric_no       TEXT NOT NULL REFERENCES students(matric_no),
    course_id       TEXT NOT NULL REFERENCES courses(id),
    session_date    TEXT NOT NULL,
    marked_at       TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'server',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(matric_no, course_id, session_date)
);

CREATE TABLE IF NOT EXISTS sync_local_state (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_devices (
    device_id       TEXT PRIMARY KEY,
    device_name     TEXT NOT NULL,
    last_sync_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);
"""

LEGACY_TABLES = [
    "attendance_logs",
    "face_embeddings",
    "face_samples",
    "course_registrations",
    "students",
    "courses",
    "levels",
    "departments",
    "courses_legacy",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def uses_uuid_schema(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn, "courses"):
        return False
    cols = _table_columns(conn, "courses")
    return "id" in cols and "course_id" not in cols


def uses_legacy_int_schema(conn: sqlite3.Connection) -> bool:
    if not _table_exists(conn, "courses"):
        return False
    cols = _table_columns(conn, "courses")
    return "course_id" in cols


def _fetch_all(conn: sqlite3.Connection, table: str) -> list[dict]:
    if not _table_exists(conn, table):
        return []
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]


def _drop_legacy_tables(conn: sqlite3.Connection) -> None:
    for table in LEGACY_TABLES:
        if _table_exists(conn, table):
            conn.execute(f"DROP TABLE {table}")


def migrate_int_schema_to_uuid(conn: sqlite3.Connection) -> None:
    """One-time migration: integer PKs -> UUID PKs with sync metadata columns."""
    if uses_uuid_schema(conn):
        return

    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")

    old_departments = _fetch_all(conn, "departments")
    old_levels = _fetch_all(conn, "levels")
    old_courses = _fetch_all(conn, "courses")
    old_students = _fetch_all(conn, "students")
    old_regs = _fetch_all(conn, "course_registrations")
    old_samples = _fetch_all(conn, "face_samples")
    old_embeddings = _fetch_all(conn, "face_embeddings")
    old_attendance = _fetch_all(conn, "attendance_logs")

    _drop_legacy_tables(conn)
    conn.executescript(UUID_SCHEMA)

    dept_map: dict[int, str] = {}
    level_map: dict[int, str] = {}
    course_map: dict[int, str] = {}

    for row in old_departments:
        old_id = int(row["department_id"])
        uid = new_uuid()
        dept_map[old_id] = uid
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO departments (id, name, code, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (uid, row["name"], row.get("code"), ts, ts),
        )

    for row in old_levels:
        old_id = int(row["level_id"])
        uid = new_uuid()
        level_map[old_id] = uid
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO levels
                (id, department_id, name, sort_order, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (uid, dept_map[int(row["department_id"])], row["name"], row["sort_order"], ts, ts),
        )

    for row in old_courses:
        old_id = int(row["course_id"])
        uid = new_uuid()
        course_map[old_id] = uid
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO courses
                (id, department_id, level_id, code, name, lecturer, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                uid,
                dept_map[int(row["department_id"])],
                level_map[int(row["level_id"])],
                row["code"],
                row["name"],
                row.get("lecturer"),
                ts,
                ts,
            ),
        )

    for row in old_students:
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO students
                (id, matric_no, full_name, department_id, level_id, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                new_uuid(),
                row["matric_no"],
                row["full_name"],
                dept_map.get(int(row["department_id"])) if row.get("department_id") else None,
                level_map.get(int(row["level_id"])) if row.get("level_id") else None,
                ts,
                ts,
            ),
        )

    for row in old_regs:
        ts = row.get("registered_at") or now
        conn.execute(
            """
            INSERT INTO course_registrations
                (id, matric_no, course_id, registered_at, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (new_uuid(), row["matric_no"], course_map[int(row["course_id"])], ts, ts, ts),
        )

    for row in old_samples:
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO face_samples
                (id, matric_no, image_path, frame_index, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (new_uuid(), row["matric_no"], row["image_path"], row.get("frame_index"), ts, ts),
        )

    for row in old_embeddings:
        ts = row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO face_embeddings
                (id, matric_no, vector, vector_dim, source_frame, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                new_uuid(),
                row["matric_no"],
                row["vector"],
                row["vector_dim"],
                row.get("source_frame"),
                ts,
                ts,
            ),
        )

    for row in old_attendance:
        ts = row.get("marked_at") or row.get("created_at") or now
        conn.execute(
            """
            INSERT INTO attendance_logs
                (id, matric_no, course_id, session_date, marked_at, source, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                new_uuid(),
                row["matric_no"],
                course_map[int(row["course_id"])],
                row["session_date"],
                row.get("marked_at") or ts,
                row.get("source") or "server",
                ts,
                ts,
            ),
        )

    conn.execute("PRAGMA foreign_keys = ON")


def ensure_uuid_schema(conn: sqlite3.Connection) -> bool:
    """Create or migrate to UUID schema. Returns True if integer->uuid migration ran."""
    if uses_uuid_schema(conn):
        conn.executescript(UUID_SCHEMA)
        return False
    if uses_legacy_int_schema(conn):
        migrate_int_schema_to_uuid(conn)
        return True
    conn.executescript(UUID_SCHEMA)
    return False
