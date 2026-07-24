"""
attendance_matcher.py
---------------------
Match a live webcam frame against enrolled students for a course using dlib encodings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from app.database import get_connection
from app.services.face_embeddings import (
    DLIB_AVAILABLE,
    blob_to_encoding,
    encoding_from_bytes,
    encoding_from_bgr,
    require_dlib,
    sync_student_embeddings,
    dlib_lock,
)

try:
    import face_recognition
except ImportError:
    face_recognition = None  # type: ignore

# Lower = stricter. 0.5 is a good balance for dlib face_recognition.
DEFAULT_TOLERANCE = 0.5

_course_index_cache: dict[str, list["KnownFace"]] = {}


@dataclass
class KnownFace:
    matric_no: str
    full_name: str
    encoding: np.ndarray


@dataclass
class MatchResult:
    matched: bool
    matric_no: str | None = None
    full_name: str | None = None
    distance: float | None = None
    reason: str = ""


def invalidate_course_cache(course_id: str | None = None) -> None:
    if course_id is None:
        _course_index_cache.clear()
    else:
        _course_index_cache.pop(course_id, None)


def _load_course_index(conn, course_id: str) -> list[KnownFace]:
    if course_id in _course_index_cache:
        return _course_index_cache[course_id]

    students = conn.execute(
        """
        SELECT DISTINCT s.matric_no, s.full_name
        FROM course_registrations cr
        JOIN students s ON s.matric_no = cr.matric_no
        WHERE cr.course_id = ? AND cr.is_deleted = 0 AND s.is_deleted = 0
        """,
        (course_id,),
    ).fetchall()

    known: list[KnownFace] = []
    for student in students:
        matric_no = student["matric_no"]
        sync_student_embeddings(conn, matric_no)

        emb_rows = conn.execute(
            "SELECT vector FROM face_embeddings WHERE matric_no = ? AND is_deleted = 0",
            (matric_no,),
        ).fetchall()

        for emb_row in emb_rows:
            known.append(
                KnownFace(
                    matric_no=matric_no,
                    full_name=student["full_name"],
                    encoding=blob_to_encoding(emb_row["vector"]),
                )
            )

    conn.commit()
    _course_index_cache[course_id] = known
    return known


def _match_query_encoding(query: np.ndarray, course_id: str, tolerance: float) -> MatchResult:
    """Compare an already-computed face encoding against a course's known faces.
    Caller must already hold dlib_lock."""
    conn = get_connection()
    try:
        known = _load_course_index(conn, course_id)
    finally:
        conn.close()

    if not known:
        return MatchResult(matched=False, reason="no_enrolled_faces")

    best_matric: str | None = None
    best_name: str | None = None
    best_distance = float("inf")

    try:
        for item in known:
            try:
                distance = float(face_recognition.face_distance([item.encoding], query)[0])
                if distance < best_distance:
                    best_distance = distance
                    best_matric = item.matric_no
                    best_name = item.full_name
            except Exception:
                continue
    except Exception as e:
        return MatchResult(matched=False, reason=f"matching_error: {str(e)}")

    if best_matric is None or best_distance > tolerance:
        return MatchResult(
            matched=False,
            reason="not_recognized",
            distance=best_distance if best_distance != float("inf") else None,
        )

    return MatchResult(
        matched=True,
        matric_no=best_matric,
        full_name=best_name,
        distance=best_distance,
    )


def match_frame_for_course(
    image_bytes: bytes,
    course_id: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> MatchResult:
    """Match a JPEG/PNG-encoded frame (e.g. uploaded from a browser)."""
    require_dlib()

    with dlib_lock:
        try:
            query = encoding_from_bytes(image_bytes)
            if query is None:
                return MatchResult(matched=False, reason="no_face_detected")
        except Exception as e:
            return MatchResult(matched=False, reason=f"encoding_error: {str(e)}")

        return _match_query_encoding(query, course_id, tolerance)


def match_bgr_frame_for_course(
    frame_bgr: np.ndarray,
    course_id: str,
    tolerance: float = DEFAULT_TOLERANCE,
) -> MatchResult:
    """Match a raw BGR numpy frame directly (e.g. captured from the Pi Camera),
    skipping the JPEG encode/decode round trip that match_frame_for_course does."""
    require_dlib()

    with dlib_lock:
        try:
            query = encoding_from_bgr(frame_bgr)
            if query is None:
                return MatchResult(matched=False, reason="no_face_detected")
        except Exception as e:
            return MatchResult(matched=False, reason=f"encoding_error: {str(e)}")

        return _match_query_encoding(query, course_id, tolerance)


def mark_attendance_for_match(
    course_id: str,
    matric_no: str,
    session_date: str | None = None,
    source: str = "server",
) -> tuple[bool, str]:
    """
    Insert attendance log. Returns (created, message).
    created=False if already marked for this date.
    """
    if session_date is None:
        session_date = date.today().isoformat()

    conn = get_connection()
    try:
        registered = conn.execute(
            """
            SELECT 1 FROM course_registrations
            WHERE matric_no = ? AND course_id = ? AND is_deleted = 0
            """,
            (matric_no, course_id),
        ).fetchone()
        if not registered:
            return False, "Student is not registered for this course."

        existing = conn.execute(
            """
            SELECT 1 FROM attendance_logs
            WHERE matric_no = ? AND course_id = ? AND session_date = ? AND is_deleted = 0
            """,
            (matric_no, course_id, session_date),
        ).fetchone()
        if existing:
            return False, "already_marked"

        from app.db_helpers import new_uuid, utc_now
        log_id = new_uuid()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO attendance_logs (id, matric_no, course_id, session_date, marked_at, source, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (log_id, matric_no, course_id, session_date, now, source, now, now),
        )
        conn.commit()
        return True, "marked"
    finally:
        conn.close()


def is_dlib_ready() -> bool:
    return DLIB_AVAILABLE