"""
routers/departments.py — CRUD for academic departments.
Levels 100L–500L are created automatically when a department is added.
"""

import sqlite3

from fastapi import APIRouter, HTTPException

from app.database import get_connection, seed_default_levels
from app.db_helpers import new_uuid, utc_now
from app.schemas import DepartmentCreate, DepartmentOut, DepartmentWithLevelsOut

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(payload: DepartmentCreate):
    conn = get_connection()
    try:
        department_id = new_uuid()
        now = utc_now()
        cur = conn.execute(
            "INSERT INTO departments (id, name, code, created_at, updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
            (department_id, payload.name, payload.code, now, now),
        )
        seed_default_levels(conn, department_id)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM departments WHERE id = ?", (department_id,)
        ).fetchone()
        return dict(row)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Department name or code already exists.") from exc
    finally:
        conn.close()


@router.get("", response_model=list[DepartmentOut])
def list_departments():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM departments WHERE is_deleted = 0 ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{department_id}", response_model=DepartmentWithLevelsOut)
def get_department(department_id: str):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM departments WHERE id = ? AND is_deleted = 0", (department_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Department not found.")

        levels = conn.execute(
            "SELECT * FROM levels WHERE department_id = ? AND is_deleted = 0 ORDER BY sort_order ASC, name ASC",
            (department_id,),
        ).fetchall()
        result = dict(row)
        result["levels"] = [dict(l) for l in levels]
        return result
    finally:
        conn.close()


@router.delete("/{department_id}", status_code=204)
def delete_department(department_id: str):
    conn = get_connection()
    try:
        from app.database import soft_delete
        success = soft_delete(conn, "departments", department_id)
        conn.commit()
        if not success:
            raise HTTPException(status_code=404, detail="Department not found.")
    finally:
        conn.close()
