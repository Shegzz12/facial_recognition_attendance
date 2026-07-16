"""
face_embeddings.py
------------------
Build and store dlib face encodings (128-d vectors) from enrollment images.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.database import get_connection

ENCODING_DIM = 128

try:
    import face_recognition

    DLIB_AVAILABLE = True
except ImportError:
    face_recognition = None  # type: ignore
    DLIB_AVAILABLE = False


def require_dlib() -> None:
    if not DLIB_AVAILABLE:
        raise RuntimeError(
            "face_recognition (dlib) is not installed. "
            "Run: pip install face-recognition"
        )


def _rgb_from_bgr(image_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def encoding_from_bgr(image_bgr: np.ndarray) -> np.ndarray | None:
    """Return the largest detected face encoding, or None."""
    require_dlib()
    rgb = _rgb_from_bgr(image_bgr)
    boxes = face_recognition.face_locations(rgb, model="hog")
    if not boxes:
        return None

    def area(box: tuple[int, int, int, int]) -> int:
        top, right, bottom, left = box
        return max(0, bottom - top) * max(0, right - left)

    largest = max(boxes, key=area)
    encodings = face_recognition.face_encodings(rgb, [largest], num_jitters=1)
    if not encodings:
        return None
    return np.asarray(encodings[0], dtype=np.float64)


def encoding_from_bytes(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        return None
    return encoding_from_bgr(image)


def encoding_from_path(image_path: str | Path) -> np.ndarray | None:
    path = Path(image_path)
    if not path.exists():
        return None
    image = cv2.imread(str(path))
    if image is None:
        return None
    return encoding_from_bgr(image)


def encoding_to_blob(encoding: np.ndarray) -> bytes:
    return np.asarray(encoding, dtype=np.float64).tobytes()


def blob_to_encoding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


def sync_student_embeddings(conn, matric_no: str) -> int:
    """
    Compute dlib encodings from all face sample images for a student
    and store any that are not already saved.
    Returns number of new embeddings stored.
    """
    require_dlib()

    rows = conn.execute(
        "SELECT sample_id, image_path FROM face_samples WHERE matric_no = ? ORDER BY sample_id",
        (matric_no,),
    ).fetchall()

    saved = 0
    for row in rows:
        exists = conn.execute(
            """
            SELECT 1 FROM face_embeddings
            WHERE matric_no = ? AND source_frame = ?
            """,
            (matric_no, row["image_path"]),
        ).fetchone()
        if exists:
            continue

        encoding = encoding_from_path(row["image_path"])
        if encoding is None:
            continue

        conn.execute(
            """
            INSERT INTO face_embeddings (matric_no, vector, vector_dim, source_frame)
            VALUES (?, ?, ?, ?)
            """,
            (matric_no, encoding_to_blob(encoding), ENCODING_DIM, row["image_path"]),
        )
        saved += 1

    return saved


def sync_all_missing_embeddings() -> int:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT matric_no FROM face_samples").fetchall()
        total = 0
        for row in rows:
            total += sync_student_embeddings(conn, row["matric_no"])
        conn.commit()
        return total
    finally:
        conn.close()
