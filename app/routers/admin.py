"""
routers/admin.py — Aggregated views for the admin dashboard.
"""

from fastapi import APIRouter, HTTPException

from app.database import get_connection
from app.schemas import CourseStatsOut, CourseStudentOut

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/courses", response_model=list[CourseStatsOut])
def list_courses_with_stats(
    department_id: str | None = None,
    level_id: str | None = None,
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

        rows = conn.execute(
            f"""
            SELECT
                c.id,
                c.code,
                c.name,
                c.lecturer,
                c.created_at,
                c.updated_at,
                c.department_id,
                d.name AS department_name,
                c.level_id,
                l.name AS level_name,
                COUNT(DISTINCT cr.matric_no) AS student_count,
                COUNT(DISTINCT al.id) AS total_attendance_marks
            FROM courses c
            JOIN departments d ON d.id = c.department_id AND d.is_deleted = 0
            JOIN levels l ON l.id = c.level_id AND l.is_deleted = 0
            LEFT JOIN course_registrations cr ON cr.course_id = c.id AND cr.is_deleted = 0
            LEFT JOIN attendance_logs al ON al.course_id = c.id AND al.is_deleted = 0
            {where}
            GROUP BY c.id
            ORDER BY d.name ASC, l.sort_order ASC, c.code ASC
            """,
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/courses/{course_id}/students", response_model=list[CourseStudentOut])
def list_course_students(course_id: str):
    conn = get_connection()
    try:
        course = conn.execute(
            "SELECT 1 FROM courses WHERE id = ? AND is_deleted = 0", (course_id,)
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found.")

        rows = conn.execute(
            """
            SELECT
                s.matric_no,
                s.full_name,
                cr.registered_at,
                (
                    SELECT COUNT(*)
                    FROM face_samples fs
                    WHERE fs.matric_no = s.matric_no AND fs.is_deleted = 0
                ) AS face_samples,
                (
                    SELECT COUNT(*)
                    FROM attendance_logs al
                    WHERE al.matric_no = s.matric_no
                      AND al.course_id = cr.course_id AND al.is_deleted = 0
                ) AS attendance_count,
                (
                    SELECT rc.card_id
                    FROM rfid_cards rc
                    WHERE rc.matric_no = s.matric_no AND rc.is_deleted = 0
                ) AS rfid_card_id
            FROM course_registrations cr
            JOIN students s ON s.matric_no = cr.matric_no AND s.is_deleted = 0
            WHERE cr.course_id = ? AND cr.is_deleted = 0
            ORDER BY cr.registered_at DESC
            """,
            (course_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
