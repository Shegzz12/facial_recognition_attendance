"""
Periodic sync agent for Raspberry Pi.

Run once:
    python scripts/sync_agent.py

Run continuously (every SYNC_INTERVAL_SECONDS):
    python scripts/sync_agent.py --loop
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

from app.config import (
    SYNC_API_KEY,
    SYNC_CLOUD_URL,
    SYNC_DEVICE_ID,
    SYNC_DEVICE_NAME,
    SYNC_INTERVAL_SECONDS,
)
from app.database import get_connection
from app.sync.engine import export_changes_since, get_last_sync_at, run_local_sync_apply, set_last_sync_at
from app.sync.constants import SYNC_LOCAL_STATE_KEY


def run_sync_once() -> dict:
    if not SYNC_CLOUD_URL:
        raise RuntimeError("SYNC_CLOUD_URL is not set in environment.")
    if not SYNC_API_KEY:
        raise RuntimeError("SYNC_API_KEY is not set in environment.")

    conn = get_connection()
    try:
        since = get_last_sync_at(conn)
        local_changes = export_changes_since(conn, since)
    finally:
        conn.close()

    payload = {
        "device_id": SYNC_DEVICE_ID,
        "device_name": SYNC_DEVICE_NAME,
        "since": since,
        "changes": local_changes,
    }

    url = f"{SYNC_CLOUD_URL}/sync"
    headers = {"X-Sync-API-Key": SYNC_API_KEY}

    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    stats = run_local_sync_apply(data["changes"], data["server_time"])
    return {
        "since": since,
        "server_time": data["server_time"],
        "pushed_tables": list(local_changes.keys()),
        "pulled_tables": list(data.get("changes", {}).keys()),
        "local_apply_stats": stats,
        "cloud_apply_stats": data.get("applied", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Raspberry Pi ↔ Cloud sync agent")
    parser.add_argument(
        "--loop",
        action="store_true",
        help=f"Run continuously every {SYNC_INTERVAL_SECONDS}s",
    )
    args = parser.parse_args()

    if args.loop:
        print(f"Sync agent running every {SYNC_INTERVAL_SECONDS}s → {SYNC_CLOUD_URL}")
        while True:
            try:
                result = run_sync_once()
                print(
                    f"[sync OK] {result['server_time']} | "
                    f"pushed={result['pushed_tables']} pulled={result['pulled_tables']}"
                )
            except Exception as exc:
                print(f"[sync ERROR] {exc}", file=sys.stderr)
            time.sleep(SYNC_INTERVAL_SECONDS)
    else:
        result = run_sync_once()
        print("Sync completed:")
        for key, value in result.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
