"""
routers/levels.py — Read-only listing of department levels (100L–500L, auto-created).
"""

from fastapi import APIRouter

from app.database import get_connection
from app.schemas import LevelOut

router = APIRouter(prefix="/levels", tags=["Levels"])


@router.get("", response_model=list[LevelOut])
def list_levels(department_id: str | None = None):
    conn = get_connection()
    try:
        if department_id is not None:
            rows = conn.execute(
                """
                SELECT * FROM levels
                WHERE department_id = ? AND is_deleted = 0
                ORDER BY sort_order ASC, name ASC
                """,
                (department_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM levels WHERE is_deleted = 0 ORDER BY sort_order ASC, name ASC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
