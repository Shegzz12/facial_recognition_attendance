"""
routers/students.py
---------------------
Basic student record creation/listing. Face capture + embeddings
come in Phase 2 (the registration webcam flow) - for now this just
handles the "name + matric number" part of registration.
"""

from fastapi import APIRouter, HTTPException
import sqlite3

from app.database import get_connection, soft_delete
from app.db_helpers import new_uuid, utc_now
from app.schemas import StudentCreate, StudentOut

router = APIRouter(prefix="/students", tags=["Students"])


@router.post("", response_model=StudentOut, status_code=201)
def create_student(student: StudentCreate):
    conn = get_connection()
    try:
        student_id = new_uuid()
        now = utc_now()
        conn.execute(
            "INSERT INTO students (id, matric_no, full_name, department_id, level_id, created_at, updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (student_id, student.matric_no, student.full_name, student.department_id, student.level_id, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409, detail=f"Student '{student.matric_no}' already exists."
        )
    finally:
        conn.close()


@router.get("", response_model=list[StudentOut])
def list_students():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM students WHERE is_deleted = 0 ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{matric_no}", response_model=StudentOut)
def get_student(matric_no: str):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM students WHERE matric_no = ?", (matric_no,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found.")
        return dict(row)
    finally:
        conn.close()


@router.delete("/{matric_no}")
def hard_delete_student(matric_no: str):
    """Hard delete a student and all associated records (face samples, embeddings,
    course registrations, attendance logs, and RFID cards)."""
    conn = get_connection()
    try:
        # Verify student exists
        student = conn.execute(
            "SELECT id FROM students WHERE matric_no = ? AND is_deleted = 0",
            (matric_no,),
        ).fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")

        # Delete face samples
        conn.execute(
            "DELETE FROM face_samples WHERE matric_no = ?",
            (matric_no,),
        )

        # Delete face embeddings
        conn.execute(
            "DELETE FROM face_embeddings WHERE matric_no = ?",
            (matric_no,),
        )

        # Delete course registrations
        conn.execute(
            "DELETE FROM course_registrations WHERE matric_no = ?",
            (matric_no,),
        )

        # Delete attendance logs
        conn.execute(
            "DELETE FROM attendance_logs WHERE matric_no = ?",
            (matric_no,),
        )

        # Delete RFID card
        conn.execute(
            "DELETE FROM rfid_cards WHERE matric_no = ?",
            (matric_no,),
        )

        # Delete the student record
        conn.execute(
            "DELETE FROM students WHERE matric_no = ?",
            (matric_no,),
        )

        conn.commit()
        return {"message": f"Student {matric_no} and all associated records have been permanently deleted."}
    finally:
        conn.close()
