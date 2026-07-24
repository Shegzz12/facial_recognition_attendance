"""
rfid_scanner.py
---------------
Runs RFID attendance scanning using the RC522 RFID reader, in a background thread,
independent of any browser tab. Designed to run *alongside* the existing
browser-based scanning and Pi camera scanning.
"""

from __future__ import annotations

import os
import threading
import time

from app.database import get_connection
from app.services.attendance_matcher import mark_attendance_for_match
from app.services.lcd_display import (
    lcd_idle,
    lcd_scanning,
    lcd_marked,
    lcd_already_marked,
    lcd_error,
    lcd_card_not_recognized,
)
from app.services import buzzer

try:
    from mfrc522 import SimpleMFRC522
    RFID_AVAILABLE = True
except ImportError:  # pragma: no cover - hardware-dependent
    SimpleMFRC522 = None  # type: ignore
    RFID_AVAILABLE = False

# How long a "not recognized" / error message lingers before reverting to the
# scanning message (both on the LCD).
RESULT_DISPLAY_SECONDS = 2.0

# How long "Attendance Mark" / "Duplicate Mark" lingers — deliberately longer
# so it's actually readable on the physical LCD.
MARK_LINGER_SECONDS = float(os.environ.get("LCD_MARK_LINGER_SECONDS", "4.0"))

# Delay between RFID reads to avoid spamming the same card
READ_DELAY_SECONDS = 2.0

# How often the reader is polled for card presence.
POLL_INTERVAL_SECONDS = float(os.environ.get("RFID_POLL_INTERVAL_SECONDS", "0.25"))

# A card has to be off the reader for this long before it counts as "removed"
# and the held alert is released — the RC522 drops the odd read even when the
# card hasn't actually moved.
CARD_ABSENCE_GRACE_SECONDS = float(os.environ.get("CARD_ABSENCE_GRACE_SECONDS", "1.0"))

BUZZER_OWNER = "rfid"

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
    "last_hex_uid": None,
    "marks_this_session": 0,
    "error": None,
}

# RFID registration scanner state
_reg_control_lock = threading.Lock()
_reg_state = {
    "running": False,
    "matric_no": None,
    "thread": None,
    "stop_event": None,
    "registered": False,
    "card_id": None,
    "error": None,
}


def _get_course(course_id: str):
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT id, code, name FROM courses WHERE id = ? AND is_deleted = 0",
            (course_id,),
        ).fetchone()
    finally:
        conn.close()


def _get_student_by_rfid(hex_uid: str):
    """Get student by RFID card hex UID."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT s.matric_no, s.full_name, rc.card_id
               FROM rfid_cards rc
               JOIN students s ON s.matric_no = rc.matric_no AND s.is_deleted = 0
               WHERE rc.hex_uid = ? AND rc.is_deleted = 0""",
            (hex_uid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _scan_loop(course_id: str, course_code: str, stop_event: threading.Event) -> None:
    reader = None
    try:
        reader = SimpleMFRC522()
        lcd_scanning()

        # lcd_reset_at: when to revert the physical LCD back to "Scanning...".
        # None = LCD is already showing the scanning message, nothing pending.
        lcd_reset_at: float | None = None

        # Presence tracking. An "episode" is one continuous presentation of one
        # card on the reader. Alerts (LCD + buzzer) are raised once per episode
        # and then held until the card is taken away — take it away and present
        # it again and the alert fires again.
        episode_uid: str | None = None
        episode_kind: str | None = None  # marked | duplicate | unknown | failed
        episode_name: str | None = None
        last_seen_at = 0.0

        _state["last_message"] = "RFID scanner ready. Hold card near reader..."

        while not stop_event.is_set():
            now = time.monotonic()

            try:
                # Non-blocking read so we can tell when the card is taken away.
                id_num = reader.read_id_no_block()
            except Exception as exc:
                _state["error"] = str(exc)
                lcd_error("RFID Error")
                lcd_reset_at = now + RESULT_DISPLAY_SECONDS
                _state["last_message"] = f"RFID error: {str(exc)}"
                buzzer.stop(BUZZER_OWNER)
                episode_uid = episode_kind = episode_name = None
                time.sleep(READ_DELAY_SECONDS)
                continue

            if id_num is None:
                # No card on the reader. Release any held alert once the card
                # has been gone long enough.
                if episode_uid is not None and now - last_seen_at >= CARD_ABSENCE_GRACE_SECONDS:
                    episode_uid = episode_kind = episode_name = None
                    buzzer.stop(BUZZER_OWNER)
                    lcd_scanning()
                    lcd_reset_at = None
                elif lcd_reset_at is not None and now >= lcd_reset_at:
                    lcd_scanning()
                    lcd_reset_at = None
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            hex_uid = hex(id_num)[2:].upper()
            last_seen_at = now
            new_episode = hex_uid != episode_uid
            if new_episode:
                buzzer.stop(BUZZER_OWNER)
                episode_uid = hex_uid
                episode_kind = None
                episode_name = None
                _state["last_hex_uid"] = hex_uid

            # ---- Held alerts: keep showing/sounding while the card stays on ----
            if episode_kind == "duplicate":
                lcd_already_marked(episode_name)
                buzzer.alarm(BUZZER_OWNER)
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if episode_kind == "unknown":
                # Keep re-showing it for as long as the card is held there; the
                # 5s buzz only fires once per presentation.
                lcd_card_not_recognized()
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            if episode_kind in ("marked", "failed"):
                if lcd_reset_at is not None and now >= lcd_reset_at:
                    lcd_scanning()
                    lcd_reset_at = None
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            # ---- First read of this presentation ----
            student = _get_student_by_rfid(hex_uid)

            if not student:
                # An unknown *card* — not an unknown face. (This used to show
                # "Face Not Recognized" on the LCD.)
                lcd_card_not_recognized()
                _state["last_message"] = "RFID card not registered."
                lcd_reset_at = None
                buzzer.beep_error(BUZZER_OWNER)
                episode_kind = "unknown"
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            episode_name = student["full_name"]

            session_date = time.strftime("%Y-%m-%d")
            created, status = mark_attendance_for_match(
                course_id, student["matric_no"], session_date, source="rfid"
            )

            if status == "already_marked":
                lcd_already_marked(student["full_name"])
                _state["last_message"] = f"{student['full_name']} already marked."
                lcd_reset_at = None
                buzzer.alarm(BUZZER_OWNER)
                episode_kind = "duplicate"
            elif created:
                lcd_marked(student["full_name"])
                _state["last_message"] = f"{student['full_name']} marked present via RFID."
                _state["marks_this_session"] += 1
                lcd_reset_at = now + MARK_LINGER_SECONDS
                buzzer.beep_success(BUZZER_OWNER)
                episode_kind = "marked"
            else:
                lcd_error("Mark Failed")
                _state["last_message"] = f"Could not mark attendance: {status}"
                lcd_reset_at = now + RESULT_DISPLAY_SECONDS
                buzzer.beep_error(BUZZER_OWNER)
                episode_kind = "failed"

            _state["last_matric"] = student["matric_no"]
            time.sleep(POLL_INTERVAL_SECONDS)

    except Exception as exc:  # pragma: no cover - hardware-dependent
        _state["error"] = str(exc)
        lcd_error("RFID Init Error")
    finally:
        buzzer.stop(BUZZER_OWNER)
        try:
            if reader:
                # Clean up reader if needed
                pass
        except Exception:
            pass
        lcd_idle()
        with _control_lock:
            _state["running"] = False
            _state["thread"] = None
            _state["stop_event"] = None


def start_scanning(course_id: str) -> dict:
    if not RFID_AVAILABLE:
        raise RuntimeError(
            "mfrc522 is not installed/available on this system. "
            "Run: pip install mfrc522 --no-deps"
        )

    course = _get_course(course_id)
    if not course:
        raise ValueError("Course not found.")

    with _control_lock:
        if _state["running"]:
            raise RuntimeError(
                f"RFID scanning is already running for {_state['course_code']}. "
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
            last_hex_uid=None,
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
            "last_hex_uid": _state["last_hex_uid"],
            "marks_this_session": _state["marks_this_session"],
            "error": _state["error"],
            "rfid_available": RFID_AVAILABLE,
            "buzzer_available": buzzer.BUZZER_AVAILABLE,
        }


# ---------- RFID Registration Scanner ----------

def _reg_scan_loop(matric_no: str, stop_event: threading.Event) -> None:
    """RFID scanner loop for card registration."""
    reader = None
    try:
        reader = SimpleMFRC522()
        lcd_scanning()

        _reg_state["last_message"] = "RFID scanner ready. Hold card near reader..."

        while not stop_event.is_set():
            try:
                # Read card - this blocks until a card is detected
                id_num, _ = reader.read()
                
                # Convert to hex string (uppercase, without '0x' prefix)
                hex_uid = hex(id_num)[2:].upper()
                
                _reg_state["last_message"] = f"Card detected: {hex_uid}. Processing..."
                
                # Check if this is the same card as last read (avoid duplicates)
                if _reg_state["last_hex_uid"] == hex_uid:
                    _reg_state["last_message"] = f"Same card detected ({hex_uid}). Please remove and try again."
                    time.sleep(READ_DELAY_SECONDS)
                    continue

                _reg_state["last_hex_uid"] = hex_uid

                # Try to register the card
                conn = get_connection()
                try:
                    # Verify student exists (trim matric_no to handle whitespace)
                    matric_no_clean = matric_no.strip()
                    student = conn.execute(
                        "SELECT full_name FROM students WHERE matric_no = ? AND is_deleted = 0",
                        (matric_no_clean,),
                    ).fetchone()
                    if not student:
                        lcd_error("Student Not Found")
                        _reg_state["last_message"] = f"Student '{matric_no_clean}' not found in database."
                        time.sleep(READ_DELAY_SECONDS)
                        continue

                    # Check if card already registered
                    existing = conn.execute(
                        "SELECT card_id FROM rfid_cards WHERE hex_uid = ? AND is_deleted = 0",
                        (hex_uid,),
                    ).fetchone()
                    if existing:
                        lcd_error("Card Registered")
                        _reg_state["last_message"] = "This card is already registered to another student."
                        time.sleep(READ_DELAY_SECONDS)
                        continue

                    # Check if student already has a card
                    existing_student_card = conn.execute(
                        "SELECT card_id FROM rfid_cards WHERE matric_no = ? AND is_deleted = 0",
                        (matric_no_clean,),
                    ).fetchone()
                    if existing_student_card:
                        lcd_error("Has Card")
                        _reg_state["last_message"] = "This student already has an RFID card."
                        time.sleep(READ_DELAY_SECONDS)
                        continue

                    # Get next card ID
                    result = conn.execute(
                        "SELECT MAX(card_id) AS max_id FROM rfid_cards WHERE is_deleted = 0"
                    ).fetchone()
                    card_id = (result["max_id"] or 0) + 1

                    # Register the card
                    from app.db_helpers import new_uuid, utc_now
                    card_uuid = new_uuid()
                    now = utc_now()
                    conn.execute(
                        """INSERT INTO rfid_cards (id, card_id, hex_uid, matric_no, created_at, updated_at, is_deleted)
                           VALUES (?, ?, ?, ?, ?, ?, 0)""",
                        (card_uuid, card_id, hex_uid, matric_no_clean, now, now),
                    )
                    conn.commit()

                    _reg_state["registered"] = True
                    _reg_state["card_id"] = card_id
                    _reg_state["last_message"] = f"Card {card_id} registered to {student['full_name']}"
                    lcd_marked(student['full_name'])
                    
                    # Stop after successful registration
                    break

                finally:
                    conn.close()

                time.sleep(READ_DELAY_SECONDS)

            except Exception as exc:
                _reg_state["error"] = str(exc)
                lcd_error("RFID Error")
                _reg_state["last_message"] = f"RFID error: {str(exc)}"
                time.sleep(READ_DELAY_SECONDS)
                continue

    except Exception as exc:  # pragma: no cover - hardware-dependent
        _reg_state["error"] = str(exc)
        _reg_state["last_message"] = f"RFID initialization error: {str(exc)}"
        lcd_error("RFID Init Error")
    finally:
        try:
            if reader:
                pass
        except Exception:
            pass
        lcd_idle()
        with _reg_control_lock:
            _reg_state["running"] = False
            _reg_state["thread"] = None
            _reg_state["stop_event"] = None


def start_registration(matric_no: str) -> dict:
    """Start RFID card registration for a specific student."""
    if not RFID_AVAILABLE:
        raise RuntimeError(
            "mfrc522 is not installed/available on this system. "
            "Run: pip install mfrc522 --no-deps"
        )

    # Trim and verify student exists
    matric_no_clean = matric_no.strip()
    conn = get_connection()
    try:
        student = conn.execute(
            "SELECT full_name FROM students WHERE matric_no = ? AND is_deleted = 0",
            (matric_no_clean,),
        ).fetchone()
        if not student:
            raise ValueError(f"Student '{matric_no_clean}' not found in database.")
    finally:
        conn.close()

    with _reg_control_lock:
        if _reg_state["running"]:
            raise RuntimeError("RFID registration is already running. Stop it first.")

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_reg_scan_loop,
            args=(matric_no_clean, stop_event),
            daemon=True,
        )
        _reg_state.update(
            running=True,
            matric_no=matric_no_clean,
            thread=thread,
            stop_event=stop_event,
            registered=False,
            card_id=None,
            error=None,
            last_hex_uid=None,
            last_message=None,
        )
        thread.start()

    return get_registration_status()


def stop_registration() -> dict:
    """Stop RFID card registration."""
    with _reg_control_lock:
        if not _reg_state["running"]:
            return get_registration_status()
        stop_event = _reg_state["stop_event"]
        thread = _reg_state["thread"]

    if stop_event:
        stop_event.set()
    if thread:
        thread.join(timeout=8)

    with _reg_control_lock:
        _reg_state["running"] = False
        _reg_state["thread"] = None
        _reg_state["stop_event"] = None

    return get_registration_status()


def get_registration_status() -> dict:
    """Get RFID registration scanner status."""
    with _reg_control_lock:
        return {
            "running": _reg_state["running"],
            "matric_no": _reg_state["matric_no"],
            "registered": _reg_state["registered"],
            "card_id": _reg_state["card_id"],
            "last_message": _reg_state.get("last_message"),
            "error": _reg_state["error"],
            "rfid_available": RFID_AVAILABLE,
        }
