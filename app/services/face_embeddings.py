"""
face_embeddings.py
------------------
Build and store dlib face encodings (128-d vectors) from enrollment images.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import cv2
import numpy as np

from app.database import get_connection

ENCODING_DIM = 128

# Face *detection* (dlib HOG) cost scales with pixel count, so we run it on a
# downscaled copy of the frame for speed — the actual face *encoding* (the
# embedding used for matching) still runs on the full-resolution crop, so
# recognition accuracy is unaffected. 0.5 = detect on a half-size (1/4 area) copy.
# Override with: export FACE_DETECTION_DOWNSCALE=0.6
DETECTION_DOWNSCALE = float(os.environ.get("FACE_DETECTION_DOWNSCALE", "0.5"))

# dlib's native (C++ / BLAS) face-detection and encoding calls are not safe to run
# concurrently from multiple threads. On Raspberry Pi / ARM this has been observed to
# corrupt the heap ("free(): corrupted unsorted chunks") and abort the whole process —
# a C-level crash that Python's try/except cannot catch. Every dlib call in the app
# (scanning, registration, embedding rebuilds) must go through this single lock.
# NOTE: must be an RLock (reentrant) — match_frame_for_course can call into this lock,
# then call sync_student_embeddings -> encoding_from_bgr, which acquires it again on
# the same thread. A plain Lock would deadlock in that case.
dlib_lock = threading.RLock()

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
    try:
        with dlib_lock:
            rgb_full = _rgb_from_bgr(image_bgr)

            if 0 < DETECTION_DOWNSCALE < 1.0:
                small_rgb = cv2.resize(
                    rgb_full, (0, 0),
                    fx=DETECTION_DOWNSCALE, fy=DETECTION_DOWNSCALE,
                    interpolation=cv2.INTER_LINEAR,
                )
            else:
                small_rgb = rgb_full

            boxes = face_recognition.face_locations(small_rgb, model="hog")
            if not boxes:
                return None

            def area(box: tuple[int, int, int, int]) -> int:
                top, right, bottom, left = box
                return max(0, bottom - top) * max(0, right - left)

            largest = max(boxes, key=area)

            if 0 < DETECTION_DOWNSCALE < 1.0:
                scale = 1.0 / DETECTION_DOWNSCALE
                top, right, bottom, left = largest
                largest = (
                    int(top * scale), int(right * scale),
                    int(bottom * scale), int(left * scale),
                )

            encodings = face_recognition.face_encodings(rgb_full, [largest], num_jitters=1)
            if not encodings:
                return None
            return np.asarray(encodings[0], dtype=np.float64)
    except Exception:
        return None


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
        "SELECT id, image_path FROM face_samples WHERE matric_no = ? AND is_deleted = 0 ORDER BY created_at",
        (matric_no,),
    ).fetchall()

    saved = 0
    for row in rows:
        exists = conn.execute(
            """
            SELECT 1 FROM face_embeddings
            WHERE matric_no = ? AND source_frame = ? AND is_deleted = 0
            """,
            (matric_no, row["image_path"]),
        ).fetchone()
        if exists:
            continue

        encoding = encoding_from_path(row["image_path"])
        if encoding is None:
            continue

        from app.db_helpers import new_uuid, utc_now
        emb_id = new_uuid()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO face_embeddings (id, matric_no, vector, vector_dim, source_frame, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (emb_id, matric_no, encoding_to_blob(encoding), ENCODING_DIM, row["image_path"], now, now),
        )
        saved += 1

    return saved


def sync_all_missing_embeddings() -> int:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT matric_no FROM face_samples WHERE is_deleted = 0").fetchall()
        total = 0
        for row in rows:
            total += sync_student_embeddings(conn, row["matric_no"])
        conn.commit()
        return total
    finally:
        conn.close()