"""Tables participating in bi-directional cloud ↔ Pi sync."""

from __future__ import annotations

from dataclasses import dataclass

SYNC_TABLE_ORDER: tuple[str, ...] = (
    "departments",
    "levels",
    "courses",
    "students",
    "course_registrations",
    "face_samples",
    "face_embeddings",
    "attendance_logs",
)

SYNC_LOCAL_STATE_KEY = "last_sync_at"


@dataclass(frozen=True)
class SyncTableConfig:
    name: str
    pk: str = "id"
    blob_columns: tuple[str, ...] = ()
    file_columns: tuple[str, ...] = ()  # local path -> base64 in payload


SYNC_TABLES: dict[str, SyncTableConfig] = {
    "departments": SyncTableConfig("departments"),
    "levels": SyncTableConfig("levels"),
    "courses": SyncTableConfig("courses"),
    "students": SyncTableConfig("students"),
    "course_registrations": SyncTableConfig("course_registrations"),
    "face_samples": SyncTableConfig("face_samples", file_columns=("image_path",)),
    "face_embeddings": SyncTableConfig("face_embeddings", blob_columns=("vector",)),
    "attendance_logs": SyncTableConfig("attendance_logs"),
}
