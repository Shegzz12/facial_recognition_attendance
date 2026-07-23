"""
Bi-directional sync engine — Last-Write-Wins on updated_at, soft-delete aware.
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Any

from app.database import DB_PATH, get_connection
from app.db_helpers import parse_ts, utc_now
from app.sync.constants import SYNC_LOCAL_STATE_KEY, SYNC_TABLE_ORDER, SYNC_TABLES

UPLOADS_DIR = DB_PATH.parent / "uploads" / "faces"


def _serialize_row(table: str, row: dict) -> dict:
    cfg = SYNC_TABLES[table]
    out = dict(row)
    for col in cfg.blob_columns:
        if out.get(col) is not None and isinstance(out[col], (bytes, memoryview)):
            out[col] = base64.b64encode(bytes(out[col])).decode("ascii")
            out[f"{col}__encoding"] = "base64"
    for col in cfg.file_columns:
        path = out.get(col)
        if path:
            file_path = Path(path)
            if not file_path.is_absolute():
                file_path = DB_PATH.parent / path
            if file_path.exists():
                out[f"{col}__b64"] = base64.b64encode(file_path.read_bytes()).decode("ascii")
    return out


def _deserialize_row(table: str, row: dict) -> dict:
    cfg = SYNC_TABLES[table]
    out = {k: v for k, v in row.items() if not k.endswith("__encoding") and not k.endswith("__b64")}
    for col in cfg.blob_columns:
        if row.get(col) is not None and row.get(f"{col}__encoding") == "base64":
            out[col] = base64.b64decode(row[col])
    for col in cfg.file_columns:
        b64_key = f"{col}__b64"
        if row.get(b64_key):
            rel = _save_synced_image(table, out, row[b64_key])
            if rel:
                out[col] = rel
    return out


def _save_synced_image(table: str, row: dict, b64_data: str) -> str | None:
    if table != "face_samples":
        return None
    matric = row.get("matric_no", "unknown").replace("/", "_")
    sample_id = row.get("id", "sample")
    dest_dir = UPLOADS_DIR / matric
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"sync_{sample_id}.jpg"
    dest.write_bytes(base64.b64decode(b64_data))
    return str(dest.relative_to(DB_PATH.parent)).replace("\\", "/")


def get_last_sync_at(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM sync_local_state WHERE key = ?",
        (SYNC_LOCAL_STATE_KEY,),
    ).fetchone()
    return row["value"] if row else None


def set_last_sync_at(conn: sqlite3.Connection, timestamp: str) -> None:
    conn.execute(
        """
        INSERT INTO sync_local_state (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (SYNC_LOCAL_STATE_KEY, timestamp),
    )


def export_changes_since(conn: sqlite3.Connection, since: str | None) -> dict[str, list[dict]]:
    """Export rows changed after `since` (includes soft-deleted rows)."""
    changes: dict[str, list[dict]] = {}
    since_dt = parse_ts(since)

    for table in SYNC_TABLE_ORDER:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        batch: list[dict] = []
        for row in rows:
            data = dict(row)
            if since and parse_ts(data.get("updated_at")) <= since_dt:
                continue
            batch.append(_serialize_row(table, data))
        if batch:
            changes[table] = batch
    return changes


def _apply_row(conn: sqlite3.Connection, table: str, incoming: dict) -> str:
    """
    Apply one record using Last-Write-Wins. Returns action: inserted|updated|skipped.
    """
    pk = SYNC_TABLES[table].pk
    record_id = incoming["id"]
    incoming = _deserialize_row(table, incoming)
    now = utc_now()

    existing = conn.execute(
        f"SELECT * FROM {table} WHERE {pk} = ?",
        (record_id,),
    ).fetchone()

    if not existing:
        cols = list(incoming.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        conn.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
            [incoming[c] for c in cols],
        )
        return "inserted"

    existing_dict = dict(existing)
    if parse_ts(incoming.get("updated_at")) <= parse_ts(existing_dict.get("updated_at")):
        return "skipped"

    set_clause = ", ".join(f"{c} = ?" for c in incoming if c != pk)
    values = [incoming[c] for c in incoming if c != pk] + [record_id]
    conn.execute(f"UPDATE {table} SET {set_clause} WHERE {pk} = ?", values)
    return "updated"


def apply_remote_changes(conn: sqlite3.Connection, changes: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    for table in SYNC_TABLE_ORDER:
        rows = changes.get(table, [])
        stats[table] = {"inserted": 0, "updated": 0, "skipped": 0}
        for row in rows:
            action = _apply_row(conn, table, row)
            stats[table][action] += 1
    return stats


def merge_sync_payload(
    local_changes: dict[str, list[dict]],
    remote_changes: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """
    Merge two change sets in table order; LWW per record id.
    Used on cloud to combine Pi push with cloud delta.
    """
    merged: dict[str, list[dict]] = {}
    for table in SYNC_TABLE_ORDER:
        by_id: dict[str, dict] = {}
        for row in remote_changes.get(table, []):
            by_id[row["id"]] = row
        for row in local_changes.get(table, []):
            rid = row["id"]
            if rid not in by_id or parse_ts(row["updated_at"]) >= parse_ts(by_id[rid].get("updated_at")):
                by_id[rid] = row
        if by_id:
            merged[table] = list(by_id.values())
    return merged


def run_local_sync_apply(remote_changes: dict[str, list[dict]], server_time: str) -> dict:
    conn = get_connection()
    try:
        stats = apply_remote_changes(conn, remote_changes)
        set_last_sync_at(conn, server_time)
        conn.commit()
        return stats
    finally:
        conn.close()


def run_cloud_sync(
    device_id: str,
    device_name: str,
    since: str | None,
    incoming_changes: dict[str, list[dict]],
) -> tuple[str, dict[str, list[dict]], dict]:
    """
    Cloud-side sync handler:
    1. Apply Pi changes
    2. Export cloud changes since `since`
    3. Return server_time + outbound changes + stats
    """
    server_time = utc_now()
    conn = get_connection()
    try:
        device = conn.execute(
            "SELECT device_id FROM sync_devices WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        if device:
            conn.execute(
                "UPDATE sync_devices SET device_name = ?, last_sync_at = ?, updated_at = ? WHERE device_id = ?",
                (device_name, server_time, server_time, device_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO sync_devices (device_id, device_name, last_sync_at, created_at, updated_at, is_deleted)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (device_id, device_name, server_time, server_time, server_time),
            )

        apply_stats = apply_remote_changes(conn, incoming_changes)
        outbound = export_changes_since(conn, since)
        conn.commit()
        return server_time, outbound, apply_stats
    finally:
        conn.close()
