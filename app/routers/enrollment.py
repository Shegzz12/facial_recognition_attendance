"""
routers/enrollment.py — Student self-registration with face capture (multi-course).
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import cv2
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.database import get_connection
from app.db_helpers import new_uuid, utc_now
from app.services.face_extractor import extract_best_face_crops, extract_face_crops_from_video
from app.services.face_embeddings import sync_student_embeddings
from app.services.attendance_matcher import invalidate_course_cache

router = APIRouter(prefix="/enrollment", tags=["Enrollment"])

FACES_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "faces"
FACES_DIR.mkdir(parents=True, exist_ok=True)

FACE_NOT_FOUND_MSG = (
    "No clear face could be found in the capture. "
    "Please make sure your face is well lit, centered, and facing the camera, then try again."
)


def _insert_course_registration(conn, matric_no: str, course_id: str) -> None:
    reg_id = new_uuid()
    now = utc_now()
    conn.execute(
        "INSERT INTO course_registrations (id, matric_no, course_id, registered_at, created_at, updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, 0)",
        (reg_id, matric_no, course_id, now, now, now),
    )


@router.post("/register")
async def register_with_face(
    matric_no: str = Form(...),
    full_name: str = Form(...),
    department_id: str = Form(...),
    level_id: str = Form(...),
    course_ids: list[str] = Form(...),
    frames: list[UploadFile] = File(default=[]),
    video: UploadFile | None = File(default=None),
):
    if not course_ids:
        raise HTTPException(status_code=422, detail="Select at least one course to register for.")

    if not frames and video is None:
        raise HTTPException(
            status_code=422,
            detail="No face capture provided. Record your face first, then submit.",
        )

    conn = get_connection()
    try:
        dept = conn.execute(
            "SELECT 1 FROM departments WHERE id = ? AND is_deleted = 0", (department_id,)
        ).fetchone()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found.")

        level = conn.execute(
            "SELECT 1 FROM levels WHERE id = ? AND department_id = ? AND is_deleted = 0",
            (level_id, department_id),
        ).fetchone()
        if not level:
            raise HTTPException(status_code=400, detail="Level does not belong to the selected department.")

        unique_course_ids = sorted(set(course_ids))
        course_rows = []
        for cid in unique_course_ids:
            row = conn.execute(
                """
                SELECT id, code, name, department_id, level_id
                FROM courses WHERE id = ? AND is_deleted = 0
                """,
                (cid,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Course id {cid} does not exist.")
            if row["department_id"] != department_id or row["level_id"] != level_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"Course {row['code']} does not belong to the selected department and level.",
                )
            course_rows.append(dict(row))

        existing = conn.execute(
            "SELECT 1 FROM students WHERE matric_no = ? AND is_deleted = 0", (matric_no,)
        ).fetchone()
        if existing:
            now = utc_now()
            conn.execute(
                """
                UPDATE students
                SET full_name = ?, department_id = ?, level_id = ?, updated_at = ?
                WHERE matric_no = ?
                """,
                (full_name, department_id, level_id, now, matric_no),
            )
        else:
            student_id = new_uuid()
            now = utc_now()
            conn.execute(
                """
                INSERT INTO students (id, matric_no, full_name, department_id, level_id, created_at, updated_at, is_deleted)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (student_id, matric_no, full_name, department_id, level_id, now, now),
            )

        registered_codes: list[str] = []
        for course in course_rows:
            already = conn.execute(
                "SELECT 1 FROM course_registrations WHERE matric_no = ? AND course_id = ? AND is_deleted = 0",
                (matric_no, course["id"]),
            ).fetchone()
            if not already:
                _insert_course_registration(conn, matric_no, course["id"])
            registered_codes.append(course["code"])
        conn.commit()

        crops: list = []

        if frames:
            frame_bytes = []
            for upload in frames:
                data = await upload.read()
                if data:
                    frame_bytes.append(data)
            if frame_bytes:
                try:
                    crops = extract_best_face_crops(frame_bytes)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

        if not crops and video is not None:
            suffix = Path(video.filename or "").suffix or ".webm"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(video.file, tmp)
                tmp_path = tmp.name
            try:
                crops = extract_face_crops_from_video(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

        if not crops:
            raise HTTPException(status_code=422, detail=FACE_NOT_FOUND_MSG)

        student_dir = FACES_DIR / matric_no.replace("/", "_")
        student_dir.mkdir(parents=True, exist_ok=True)

        existing_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM face_samples WHERE matric_no = ? AND is_deleted = 0", (matric_no,)
        ).fetchone()["cnt"]

        saved_paths = []
        for i, crop in enumerate(crops):
            idx = existing_count + i
            filename = f"{matric_no.replace('/', '_')}_{idx}.jpg"
            filepath = student_dir / filename
            cv2.imwrite(str(filepath), crop)
            saved_paths.append(str(filepath))

            sample_id = new_uuid()
            now = utc_now()
            conn.execute(
                "INSERT INTO face_samples (id, matric_no, image_path, frame_index, created_at, updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, 0)",
                (sample_id, matric_no, str(filepath), idx, now, now),
            )
        conn.commit()

        try:
            sync_student_embeddings(conn, matric_no)
            conn.commit()
        except Exception as exc:
            # dlib may be missing or a sample image unreadable — registration still succeeds.
            print(f"[enrollment] Embedding sync skipped for {matric_no}: {exc}")

        for course in course_rows:
            invalidate_course_cache(course["id"])

        course_label = ", ".join(registered_codes)
        return {
            "matric_no": matric_no,
            "full_name": full_name,
            "department_id": department_id,
            "level_id": level_id,
            "course_ids": [c["id"] for c in course_rows],
            "courses_registered": registered_codes,
            "face_samples_saved": len(saved_paths),
            "message": (
                f"Registered successfully for {len(course_rows)} course(s): {course_label}. "
                f"Saved {len(saved_paths)} face sample(s)."
            ),
        }

    finally:
        conn.close()
