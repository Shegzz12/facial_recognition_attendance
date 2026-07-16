"""
routers/registrations.py
--------------------------
Links a student to a course. This is what happens when a student
fills the "register for this course" form (name + matric no. part;
face video comes in Phase 2).
"""

from fastapi import APIRouter, HTTPException
import sqlite3

from app.database import get_connection, soft_delete
from app.db_helpers import new_uuid, utc_now
from app.schemas import RegistrationCreate, RegistrationOut

router = APIRouter(prefix="/registrations", tags=["Registrations"])


@router.post("", response_model=RegistrationOut, status_code=201)
def register_student_for_course(reg: RegistrationCreate):
    conn = get_connection()
    try:
        # Confirm student and course both exist, with clear error messages.
        student = conn.execute(
            "SELECT 1 FROM students WHERE matric_no = ? AND is_deleted = 0", (reg.matric_no,)
        ).fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student does not exist. Create the student first.")

        course = conn.execute(
            "SELECT 1 FROM courses WHERE id = ? AND is_deleted = 0", (reg.course_id,)
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Course does not exist.")

        reg_id = new_uuid()
        now = utc_now()
        conn.execute(
            "INSERT INTO course_registrations (id, matric_no, course_id, registered_at, created_at, updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (reg_id, reg.matric_no, reg.course_id, now, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM course_registrations WHERE id = ?",
            (reg_id,),
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="This student is already registered for this course.",
        )
    finally:
        conn.close()


@router.get("/course/{course_id}", response_model=list[RegistrationOut])
def list_registrations_for_course(course_id: str):
    """Useful later for the 'Export for Pi' step: get everyone registered for a course."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM course_registrations WHERE course_id = ? AND is_deleted = 0", (course_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
