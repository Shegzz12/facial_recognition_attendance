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
