"""
routers/rfid.py
---------------
RFID card registration and management endpoints.
"""

from fastapi import APIRouter, HTTPException, Form
import sqlite3

from app.database import get_connection
from app.db_helpers import new_uuid, utc_now
from app.schemas import RFIDCardCreate, RFIDCardOut, RFIDCardRegistrationOut
from app.services import rfid_scanner

router = APIRouter(prefix="/rfid", tags=["RFID"])


def _get_next_card_id(conn: sqlite3.Connection) -> int:
    """Get the next sequential card ID (1-based)."""
    result = conn.execute(
        "SELECT MAX(card_id) AS max_id FROM rfid_cards WHERE is_deleted = 0"
    ).fetchone()
    return (result["max_id"] or 0) + 1


@router.post("/register", response_model=RFIDCardRegistrationOut, status_code=201)
def register_rfid_card(card: RFIDCardCreate):
    """Register an RFID card to a student by matric number."""
    conn = get_connection()
    try:
        # Verify student exists
        student = conn.execute(
            "SELECT full_name FROM students WHERE matric_no = ? AND is_deleted = 0",
            (card.matric_no,),
        ).fetchone()
        if not student:
            raise HTTPException(
                status_code=404, detail=f"Student with matric number '{card.matric_no}' not found."
            )

        # Check if card hex_uid is already registered
        existing = conn.execute(
            "SELECT matric_no FROM rfid_cards WHERE hex_uid = ? AND is_deleted = 0",
            (card.hex_uid,),
        ).fetchone()
        if existing:
            raise HTTPException(
                status_code=409, detail="This RFID card is already registered to another student."
            )

        # Check if student already has a card
        existing_student_card = conn.execute(
            "SELECT card_id FROM rfid_cards WHERE matric_no = ? AND is_deleted = 0",
            (card.matric_no,),
        ).fetchone()
        if existing_student_card:
            raise HTTPException(
                status_code=409, detail="This student already has an RFID card registered."
            )

        # Get next card ID
        card_id = _get_next_card_id(conn)
        
        # Register the card
        card_uuid = new_uuid()
        now = utc_now()
        conn.execute(
            """INSERT INTO rfid_cards (id, card_id, hex_uid, matric_no, created_at, updated_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (card_uuid, card_id, card.hex_uid, card.matric_no, now, now),
        )
        conn.commit()

        return {
            "card_id": card_id,
            "matric_no": card.matric_no,
            "full_name": student["full_name"],
            "message": f"RFID card {card_id} successfully registered to {student['full_name']} ({card.matric_no}).",
        }
    finally:
        conn.close()


@router.get("/cards", response_model=list[RFIDCardOut])
def list_rfid_cards():
    """List all registered RFID cards."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM rfid_cards WHERE is_deleted = 0 ORDER BY card_id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/card/{hex_uid}", response_model=RFIDCardOut)
def get_rfid_card(hex_uid: str):
    """Get RFID card details by hex UID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM rfid_cards WHERE hex_uid = ? AND is_deleted = 0",
            (hex_uid,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RFID card not found.")
        return dict(row)
    finally:
        conn.close()


@router.get("/student/{matric_no}", response_model=RFIDCardOut)
def get_student_rfid_card(matric_no: str):
    """Get RFID card for a student by matric number."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM rfid_cards WHERE matric_no = ? AND is_deleted = 0",
            (matric_no,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No RFID card registered for this student.")
        return dict(row)
    finally:
        conn.close()


@router.post("/register/start")
def start_rfid_registration(matric_no: str = Form(...)):
    """Start RFID card registration scanner for a specific student."""
    try:
        return rfid_scanner.start_registration(matric_no)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/register/stop")
def stop_rfid_registration():
    """Stop RFID card registration scanner."""
    return rfid_scanner.stop_registration()


@router.get("/register/status")
def get_rfid_registration_status():
    """Get RFID registration scanner status."""
    return rfid_scanner.get_registration_status()
