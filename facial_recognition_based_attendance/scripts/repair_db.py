"""
One-off repair script for databases left in a broken migration state.

Run:
    python scripts/repair_db.py
"""

from app.database import DB_PATH, get_connection, init_db, repair_legacy_course_fk_references


def main() -> None:
    print(f"Checking database: {DB_PATH}")
    init_repaired = init_db()
    if init_repaired:
        print(f"init_db repaired: {', '.join(init_repaired)}")
        return

    conn = get_connection()
    try:
        repaired = repair_legacy_course_fk_references(conn)
        conn.commit()
        if repaired:
            print(f"Repaired FK on: {', '.join(repaired)}")
        else:
            print("No stale courses_legacy foreign keys found. Database looks OK.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
