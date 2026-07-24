"""
pi_camera_scanner.py
---------------------
Runs face-recognition attendance scanning using the Raspberry Pi's own camera
(Camera Module via picamera2), in a background thread, independent of any
browser tab. Designed to run *alongside* the existing browser-based scanning —
both paths share the same dlib_lock (see face_embeddings.py), so they never
touch dlib at the same time, but can otherwise run concurrently.

Also exposes the live camera feed (with a status banner baked in) so the
browser can show it as an MJPEG stream while scanning is active.
"""

from __future__ import annotations

import os
import threading
import time

import cv2

from app.database import get_connection
from app.services.attendance_matcher import (
    DEFAULT_TOLERANCE,
    is_dlib_ready,
    match_bgr_frame_for_course,
    mark_attendance_for_match,
)
from app.services.lcd_display import (
    lcd_idle,
    lcd_scanning,
    lcd_no_face,
    lcd_not_recognized,
    lcd_marked,
    lcd_already_marked,
    lcd_error,
)
from app.services import buzzer

try:
    from picamera2 import Picamera2

    PICAMERA_AVAILABLE = True
except ImportError:  # pragma: no cover - hardware-dependent
    Picamera2 = None  # type: ignore
    PICAMERA_AVAILABLE = False

# How often we attempt a recognition pass. Lowered from 2.0s now that detection
# is faster (see DETECTION_DOWNSCALE in face_embeddings.py).
SCAN_INTERVAL_SECONDS = 1.0

# How long a "not recognized" / error message lingers before reverting to the
# scanning message (both on the LCD and as a banner baked into the video feed).
RESULT_DISPLAY_SECONDS = 2.0

# How long "Attendance Mark" / "Duplicate Mark" lingers — deliberately longer
# so it's actually readable on the physical LCD, per request (4+ seconds).
MARK_LINGER_SECONDS = float(os.environ.get("LCD_MARK_LINGER_SECONDS", "4.0"))

# A face has to be missing for this long before we treat it as "removed" and
# clear the current alert — a single dropped detection shouldn't cancel it.
FACE_ABSENCE_GRACE_SECONDS = float(os.environ.get("FACE_ABSENCE_GRACE_SECONDS", "2.0"))

# Set to 1 to also raise the duplicate alert for the student who was *just*
# marked while they're still standing in front of the camera. Off by default so
# a successful mark isn't immediately followed by the duplicate alarm.
ALERT_DUPLICATE_AFTER_MARK = os.environ.get("ALERT_DUPLICATE_AFTER_MARK", "0") not in (
    "0",
    "false",
    "False",
)

BUZZER_OWNER = "camera"

# Alerts that persist stay on screen until the face is removed, so their banner
# is simply given a far-future expiry and cleared explicitly.
_PERSISTENT_BANNER_SECONDS = 3600.0

PREVIEW_JPEG_QUALITY = 70

# BGR colors for the banner background
_COLOR_SUCCESS = (60, 170, 60)
_COLOR_ERROR = (50, 50, 210)
_COLOR_INFO = (0, 140, 220)

_control_lock = threading.Lock()
_state = {
    "running": False,
    "course_id": None,
    "course_code": None,
    "course_name": None,
    "thread": None,
    "stop_event": None,
    "started_at": None,
    "last_message": None,
    "last_matric": None,
    "marks_this_session": 0,
    "error": None,
}

_frame_lock = threading.Lock()
_latest_frame_jpeg: bytes | None = None


def _get_course(course_id: str):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, code, name FROM courses WHERE id = ? AND is_deleted = 0",
            (course_id,),
        ).fetchone()
    finally:
        conn.close()


def _draw_banner(frame_bgr, top_label: str, banner_text: str | None, banner_color) -> "cv2.typing.MatLike":
    """Bake a small top label (course code — video only, never the LCD) and,
    if present, a bottom status banner directly into the frame before it gets
    JPEG-encoded for streaming."""
    frame = frame_bgr.copy()
    h, w = frame.shape[:2]

    cv2.rectangle(frame, (0, 0), (w, 28), (30, 30, 30), -1)
    cv2.putText(frame, top_label, (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    if banner_text:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, h - 40), (w, h), banner_color, -1)
        cv2.addWeighted(overlay, 0.8, frame, 0.2, 0, frame)
        cv2.putText(frame, banner_text, (10, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA)

    return frame


def _publish_frame(frame_bgr, top_label: str, banner_text: str | None, banner_color) -> None:
    global _latest_frame_jpeg
    annotated = _draw_banner(frame_bgr, top_label, banner_text, banner_color)
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_JPEG_QUALITY])
    if ok:
        with _frame_lock:
            _latest_frame_jpeg = buf.tobytes()


def get_latest_frame_jpeg() -> bytes | None:
    with _frame_lock:
        return _latest_frame_jpeg


def _scan_loop(course_id: str, course_code: str, stop_event: threading.Event) -> None:
    global _latest_frame_jpeg
    picam2 = Picamera2()
    try:
        config = picam2.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        picam2.configure(config)
        picam2.start()
        time.sleep(1.5)  # let auto-exposure/white-balance settle

        top_label = f"{course_code} - LIVE"  # video overlay only, never the LCD
        lcd_scanning()

        # banner_text/banner_color/banner_until: what's baked into the live
        # video preview right now (independent of the LCD's own timing).
        banner_text = None
        banner_color = _COLOR_INFO
        banner_until = 0.0

        # lcd_reset_at: when to revert the physical LCD back to "Scanning...".
        # None = LCD is already showing the scanning message, nothing pending.
        lcd_reset_at: float | None = None

        # Presence tracking. An "episode" is one continuous appearance of one
        # subject in front of the camera: the same student, or the same
        # unrecognized face. Alerts (LCD + buzzer) are raised once per episode
        # and then held until the face is removed — remove and present again
        # and the alert fires again.
        episode_key: str | None = None
        episode_kind: str | None = None  # marked | duplicate | unknown | no_faces | failed
        last_seen_at = 0.0

        def end_episode() -> None:
            buzzer.stop(BUZZER_OWNER)
            lcd_scanning()

        next_scan_at = 0.0

        while not stop_event.is_set():
            # NOTE: Picamera2's "RGB888" format actually delivers pixel data in
            # BGR channel order (a documented quirk) — exactly what our
            # OpenCV/dlib pipeline expects, so we pass it straight through.
            frame_bgr = picam2.capture_array()
            now = time.monotonic()

            # Keep the video feed live every loop iteration, independent of
            # whether a recognition pass runs this iteration.
            active_banner = banner_text if now < banner_until else None
            _publish_frame(frame_bgr, top_label, active_banner, banner_color)

            # Revert the LCD once its hold time has elapsed — checked every
            # iteration so it happens on time without blocking the camera loop.
            if lcd_reset_at is not None and now >= lcd_reset_at:
                lcd_scanning()
                lcd_reset_at = None

            if now < next_scan_at:
                time.sleep(0.03)
                continue
            next_scan_at = now + SCAN_INTERVAL_SECONDS

            try:
                result = match_bgr_frame_for_course(frame_bgr, course_id, DEFAULT_TOLERANCE)
            except Exception as exc:
                _state["error"] = str(exc)
                lcd_error(str(exc)[:16])
                lcd_reset_at = now + RESULT_DISPLAY_SECONDS
                banner_text, banner_color = f"Error: {str(exc)[:40]}", _COLOR_ERROR
                banner_until = now + RESULT_DISPLAY_SECONDS
                continue

            if stop_event.is_set():
                break

            # ---- Who (if anyone) is currently in front of the camera? ----
            if result.matched:
                present_key = f"student:{result.matric_no}"
            elif result.reason == "no_face_detected":
                present_key = None
            elif result.reason == "no_enrolled_faces":
                present_key = "no_faces"
            else:
                present_key = "unknown"

            if present_key is None:
                # Don't touch the LCD or banner for empty frames — this happens
                # constantly while no one is in front of the camera. Once the
                # face has been gone long enough, any held alert is released.
                _state["last_message"] = "No face detected."
                if episode_key is not None and now - last_seen_at >= FACE_ABSENCE_GRACE_SECONDS:
                    episode_key = None
                    episode_kind = None
                    end_episode()
                    lcd_reset_at = None
                    banner_text = None
                    banner_until = 0.0
                continue

            last_seen_at = now
            new_episode = present_key != episode_key
            if new_episode:
                buzzer.stop(BUZZER_OWNER)
                episode_key = present_key
                episode_kind = None

            if present_key == "no_faces":
                lcd_error("No Faces Set")
                _state["last_message"] = "No enrolled faces with data for this course."
                banner_text, banner_color = "No enrolled face data for this course", _COLOR_ERROR
                banner_until = now + _PERSISTENT_BANNER_SECONDS
                lcd_reset_at = None
                if new_episode:
                    buzzer.beep_error(BUZZER_OWNER)
                episode_kind = "no_faces"
                continue

            if present_key == "unknown":
                # Keep re-showing "not recognized" for as long as the face stays
                # in front of the camera; the 5s buzz only fires once per
                # appearance.
                lcd_not_recognized()
                _state["last_message"] = "Face not recognized."
                banner_text, banner_color = "Face not recognized", _COLOR_ERROR
                banner_until = now + _PERSISTENT_BANNER_SECONDS
                lcd_reset_at = None
                if new_episode:
                    buzzer.beep_error(BUZZER_OWNER)
                episode_kind = "unknown"
                continue

            # ---- A known student is in frame ----
            _state["last_matric"] = result.matric_no

            if episode_kind == "duplicate":
                # Held duplicate alert: keep the name + "Duplicate Mark" on the
                # LCD and the buzzer sounding until the face is removed.
                lcd_already_marked(result.full_name)
                banner_text = f"Already marked: {result.full_name}"
                banner_color = _COLOR_INFO
                banner_until = now + _PERSISTENT_BANNER_SECONDS
                buzzer.alarm(BUZZER_OWNER)
                continue

            if episode_kind == "marked" and not ALERT_DUPLICATE_AFTER_MARK:
                # Just marked and still standing there — stay quiet until they
                # step away (set ALERT_DUPLICATE_AFTER_MARK=1 to alert instead).
                continue

            created, status = mark_attendance_for_match(
                course_id, result.matric_no, source="pi_camera"
            )

            if status == "already_marked":
                lcd_already_marked(result.full_name)
                _state["last_message"] = f"{result.full_name} already marked."
                banner_text, banner_color = f"Already marked: {result.full_name}", _COLOR_INFO
                banner_until = now + _PERSISTENT_BANNER_SECONDS
                lcd_reset_at = None
                buzzer.alarm(BUZZER_OWNER)
                episode_kind = "duplicate"
            elif created:
                lcd_marked(result.full_name)
                _state["last_message"] = f"{result.full_name} marked present."
                _state["marks_this_session"] += 1
                banner_text, banner_color = f"MARKED: {result.full_name}", _COLOR_SUCCESS
                lcd_reset_at = now + MARK_LINGER_SECONDS
                banner_until = now + MARK_LINGER_SECONDS
                buzzer.beep_success(BUZZER_OWNER)
                episode_kind = "marked"
            else:
                lcd_error("Mark Failed")
                _state["last_message"] = f"Could not mark attendance: {status}"
                banner_text, banner_color = "Could not mark attendance", _COLOR_ERROR
                banner_until = now + _PERSISTENT_BANNER_SECONDS
                lcd_reset_at = None
                buzzer.beep_error(BUZZER_OWNER)
                episode_kind = "failed"

    except Exception as exc:  # pragma: no cover - hardware-dependent
        _state["error"] = str(exc)
        lcd_error("camera error")
    finally:
        buzzer.stop(BUZZER_OWNER)
        try:
            picam2.stop()
            picam2.close()
        except Exception:
            pass
        lcd_idle()
        with _frame_lock:
            _latest_frame_jpeg = None
        with _control_lock:
            _state["running"] = False
            _state["thread"] = None
            _state["stop_event"] = None


def start_scanning(course_id: str) -> dict:
    if not PICAMERA_AVAILABLE:
        raise RuntimeError(
            "picamera2 is not installed/available on this system. "
            "Run: sudo apt install -y python3-picamera2"
        )
    if not is_dlib_ready():
        raise RuntimeError("face_recognition (dlib) is not installed on the server.")

    course = _get_course(course_id)
    if not course:
        raise ValueError("Course not found.")

    with _control_lock:
        if _state["running"]:
            raise RuntimeError(
                f"Pi camera scanning is already running for {_state['course_code']}. "
                "Stop it first."
            )

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_scan_loop,
            args=(course_id, course["code"], stop_event),
            daemon=True,
        )
        _state.update(
            running=True,
            course_id=course_id,
            course_code=course["code"],
            course_name=course["name"],
            thread=thread,
            stop_event=stop_event,
            started_at=time.time(),
            last_message=None,
            last_matric=None,
            marks_this_session=0,
            error=None,
        )
        thread.start()

    return get_status()


def stop_scanning() -> dict:
    with _control_lock:
        if not _state["running"]:
            return get_status()
        stop_event = _state["stop_event"]
        thread = _state["thread"]

    if stop_event:
        stop_event.set()
    if thread:
        thread.join(timeout=8)

    with _control_lock:
        _state["running"] = False
        _state["thread"] = None
        _state["stop_event"] = None

    return get_status()


def get_status() -> dict:
    with _control_lock:
        return {
            "running": _state["running"],
            "course_id": _state["course_id"],
            "course_code": _state["course_code"],
            "course_name": _state["course_name"],
            "started_at": _state["started_at"],
            "last_message": _state["last_message"],
            "last_matric": _state["last_matric"],
            "marks_this_session": _state["marks_this_session"],
            "error": _state["error"],
            "picamera_available": PICAMERA_AVAILABLE,
            "buzzer_available": buzzer.BUZZER_AVAILABLE,
        }