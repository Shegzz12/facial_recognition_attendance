"""
routers/attendance.py
-----------------------
Attendance marking, session setup, and live face-scan recognition (dlib).
"""

import asyncio
import sqlite3
from datetime import date
import time

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse

from app.database import get_connection, soft_delete
from app.db_helpers import new_uuid, utc_now

from app.schemas import AttendanceMark, AttendanceOut, AttendanceSessionOut, AttendanceScanOut

from app.services.attendance_matcher import (
    DEFAULT_TOLERANCE,
    is_dlib_ready,
    invalidate_course_cache,
    mark_attendance_for_match,
    match_frame_for_course,
)
from app.services.face_embeddings import sync_all_missing_embeddings
from app.services import pi_camera_scanner
from app.services import rfid_scanner

router = APIRouter(prefix="/attendance", tags=["Attendance"])


def _today() -> str:
    return date.today().isoformat()


@router.get("/session/{course_id}", response_model=AttendanceSessionOut)
def get_attendance_session(course_id: str):
    conn = get_connection()
    try:
        course = conn.execute(
            """
            SELECT c.id, c.code, c.name, d.name AS department_name, l.name AS level_name
            FROM courses c
            JOIN departments d ON d.id = c.department_id AND d.is_deleted = 0
            JOIN levels l ON l.id = c.level_id AND l.is_deleted = 0
            WHERE c.id = ? AND c.is_deleted = 0
            """,
            (course_id,),
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found.")

        enrolled = conn.execute(
            "SELECT COUNT(DISTINCT matric_no) AS cnt FROM course_registrations WHERE course_id = ? AND is_deleted = 0",
            (course_id,),
        ).fetchone()["cnt"]

        with_faces = conn.execute(
            """
            SELECT COUNT(DISTINCT cr.matric_no) AS cnt
            FROM course_registrations cr
            JOIN face_embeddings fe ON fe.matric_no = cr.matric_no AND fe.is_deleted = 0
            WHERE cr.course_id = ? AND cr.is_deleted = 0
            """,
            (course_id,),
        ).fetchone()["cnt"]

        marked_today = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM attendance_logs
            WHERE course_id = ? AND session_date = ? AND is_deleted = 0
            """,
            (course_id, _today()),
        ).fetchone()["cnt"]

        return {
            "course_id": course["id"],
            "code": course["code"],
            "name": course["name"],
            "department_name": course["department_name"],
            "level_name": course["level_name"],
            "session_date": _today(),
            "enrolled_students": enrolled,
            "students_with_faces": with_faces,
            "marked_today": marked_today,
            "dlib_ready": is_dlib_ready(),
        }
    finally:
        conn.close()


@router.post("/scan", response_model=AttendanceScanOut)
async def scan_face_for_attendance(
    course_id: str = Form(...),
    frame: UploadFile = File(...),
):
    if not is_dlib_ready():
        raise HTTPException(
            status_code=503,
            detail="dlib/face_recognition is not installed on the server. Run: pip install face-recognition",
        )

    conn = get_connection()
    try:
        course = conn.execute(
            "SELECT code, name FROM courses WHERE id = ? AND is_deleted = 0", (course_id,)
        ).fetchone()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found.")
    finally:
        conn.close()

    image_bytes = await frame.read()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Empty frame received.")

    # dlib matching is CPU-heavy — run off the async event loop.
    try:
        match = await asyncio.to_thread(
            match_frame_for_course, image_bytes, course_id, DEFAULT_TOLERANCE
        )
    except Exception as e:
        # dlib memory corruption on ARM - return graceful error instead of crashing
        return {
            "matched": False,
            "marked": False,
            "already_marked": False,
            "course_id": course_id,
            "session_date": _today(),
            "message": f"Face recognition error: {str(e)}. This may be due to dlib memory issues on ARM. Try restarting the server.",
            "distance": None,
        }
    session_date = _today()

    if not match.matched:
        messages = {
            "no_face_detected": "No face detected. Look directly at the camera.",
            "no_enrolled_faces": "No enrolled students with face data for this course.",
            "not_recognized": "Face not recognized. Only registered students can mark attendance.",
        }
        return {
            "matched": False,
            "marked": False,
            "already_marked": False,
            "course_id": course_id,
            "session_date": session_date,
            "message": messages.get(match.reason, "Face not recognized."),
            "distance": match.distance,
        }

    created, status = mark_attendance_for_match(course_id, match.matric_no, session_date)

    if status == "already_marked":
        return {
            "matched": True,
            "marked": False,
            "already_marked": True,
            "matric_no": match.matric_no,
            "full_name": match.full_name,
            "course_id": course_id,
            "session_date": session_date,
            "message": f"{match.full_name} ({match.matric_no}) — attendance already marked today for {course['code']}.",
            "distance": match.distance,
        }

    if not created:
        raise HTTPException(status_code=400, detail=status)

    return {
        "matched": True,
        "marked": True,
        "already_marked": False,
        "matric_no": match.matric_no,
        "full_name": match.full_name,
        "course_id": course_id,
        "session_date": session_date,
        "message": f"Attendance marked successfully for {match.full_name} ({match.matric_no}).",
        "distance": match.distance,
    }


@router.post("/rebuild-embeddings")
def rebuild_face_embeddings():
    """Admin utility: rebuild dlib embeddings from stored face sample images."""
    if not is_dlib_ready():
        raise HTTPException(status_code=503, detail="dlib/face_recognition is not installed.")

    count = sync_all_missing_embeddings()
    invalidate_course_cache()
    return {"embeddings_added": count, "message": f"Built {count} new face embedding(s)."}

@router.post("/pi-scan/start")
def start_pi_camera_scan(course_id: str = Form(...)):
    """Start background attendance scanning using the Pi's own camera + LCD.
    Runs independently of any browser tab, and alongside browser-based scanning."""
    try:
        return pi_camera_scanner.start_scanning(course_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/pi-scan/stop")
def stop_pi_camera_scan():
    return pi_camera_scanner.stop_scanning()


@router.get("/pi-scan/status")
def pi_camera_scan_status():
    return pi_camera_scanner.get_status()


@router.post("/rfid-scan/start")
def start_rfid_scan(course_id: str = Form(...)):
    """Start background RFID attendance scanning using the RC522 reader.
    Runs independently of any browser tab, and alongside camera-based scanning."""
    try:
        return rfid_scanner.start_scanning(course_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/rfid-scan/stop")
def stop_rfid_scan():
    return rfid_scanner.stop_scanning()


@router.get("/rfid-scan/status")
def rfid_scan_status():
    return rfid_scanner.get_status()


def _mjpeg_frame_generator():
    boundary = b"--frame"
    # Stop naturally once scanning is no longer running, rather than streaming forever.
    while pi_camera_scanner.get_status()["running"]:
        frame = pi_camera_scanner.get_latest_frame_jpeg()
        if frame is not None:
            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n" +
                frame + b"\r\n"
            )
        time.sleep(0.07)  # ~14 fps cap on the stream, independent of scan interval


@router.get("/pi-scan/stream")
def pi_camera_stream():
    """Live MJPEG preview of what the Pi camera currently sees, with the same
    marked/not-recognized status baked in that's shown on the LCD."""
    if not pi_camera_scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="Pi camera scanning is not running.")
    return StreamingResponse(
        _mjpeg_frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("", response_model=AttendanceOut, status_code=201)
def mark_attendance(entry: AttendanceMark):
    conn = get_connection()
    try:
        log_id = new_uuid()
        now = utc_now()
        cur = conn.execute(
            """INSERT INTO attendance_logs (id, matric_no, course_id, session_date, marked_at, source, created_at, updated_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (log_id, entry.matric_no, entry.course_id, entry.session_date, now, entry.source, now, now),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM attendance_logs WHERE id = ?", (log_id,)
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Attendance already marked for this student, course, and date.",
        )
    finally:
        conn.close()


@router.get("/course/{course_id}", response_model=list[AttendanceOut])
def list_attendance_for_course(course_id: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM attendance_logs WHERE course_id = ? AND is_deleted = 0 ORDER BY session_date DESC",
            (course_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/student/{matric_no}", response_model=list[AttendanceOut])
def list_attendance_for_student(matric_no: str):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM attendance_logs WHERE matric_no = ? AND is_deleted = 0 ORDER BY session_date DESC",
            (matric_no,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
