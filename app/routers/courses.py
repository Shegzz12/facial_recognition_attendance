"""
routers/courses.py — Course management scoped to department + level.
"""

import sqlite3

from fastapi import APIRouter, HTTPException, Query

from app.database import get_connection, soft_delete
from app.db_helpers import new_uuid, utc_now
from app.schemas import CourseCreate, CourseOut

router = APIRouter(prefix="/courses", tags=["Courses"])


def _course_row_to_dict(row) -> dict:
    data = dict(row)
    return data


def _fetch_courses(conn, where_clause: str = "", params: tuple = ()):
    query = f"""
        SELECT
            c.*,
            d.name AS department_name,
            l.name AS level_name
        FROM courses c
        JOIN departments d ON d.id = c.department_id AND d.is_deleted = 0
        JOIN levels l ON l.id = c.level_id AND l.is_deleted = 0
        {where_clause}
        ORDER BY d.name ASC, l.sort_order ASC, c.code ASC
    """
    rows = conn.execute(query, params).fetchall()
    return [_course_row_to_dict(r) for r in rows]


@router.post("", response_model=CourseOut, status_code=201)
def create_course(course: CourseCreate):
    conn = get_connection()
    try:
        dept = conn.execute(
            "SELECT 1 FROM departments WHERE id = ? AND is_deleted = 0", (course.department_id,)
        ).fetchone()
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found.")

        level = conn.execute(
            "SELECT 1 FROM levels WHERE id = ? AND department_id = ? AND is_deleted = 0",
            (course.level_id, course.department_id),
        ).fetchone()
        if not level:
            raise HTTPException(
                status_code=400,
                detail="Level does not belong to the selected department.",
            )

        course_id = new_uuid()
        now = utc_now()
        conn.execute(
            """
            INSERT INTO courses (id, department_id, level_id, code, name, lecturer, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (course_id, course.department_id, course.level_id, course.code, course.name, course.lecturer, now, now),
        )
        conn.commit()
        rows = _fetch_courses(conn, "WHERE c.id = ?", (course_id,))
        return rows[0]
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Course code '{course.code}' already exists for this department and level.",
        ) from exc
    finally:
        conn.close()


@router.get("", response_model=list[CourseOut])
def list_courses(
    department_id: str | None = Query(default=None),
    level_id: str | None = Query(default=None),
):
    conn = get_connection()
    try:
        clauses = ["c.is_deleted = 0"]
        params: list = []
        if department_id is not None:
            clauses.append("c.department_id = ?")
            params.append(department_id)
        if level_id is not None:
            clauses.append("c.level_id = ?")
            params.append(level_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return _fetch_courses(conn, where, tuple(params))
    finally:
        conn.close()


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: str):
    conn = get_connection()
    try:
        rows = _fetch_courses(conn, "WHERE c.id = ?", (course_id,))
        if not rows:
            raise HTTPException(status_code=404, detail="Course not found.")
        return rows[0]
    finally:
        conn.close()


@router.delete("/{course_id}", status_code=204)
def delete_course(course_id: str):
    conn = get_connection()
    try:
        success = soft_delete(conn, "courses", course_id)
        conn.commit()
        if not success:
            raise HTTPException(status_code=404, detail="Course not found.")
    finally:
        conn.close()
