"""
Cloud /sync endpoint — Raspberry Pi pushes local changes and pulls cloud changes.
"""

from fastapi import APIRouter, Header, HTTPException

from app.config import SYNC_API_KEY
from app.schemas import SyncPullResponse, SyncPushRequest
from app.sync.engine import run_cloud_sync

router = APIRouter(prefix="/sync", tags=["Sync"])


def _verify_api_key(api_key: str | None) -> None:
    if not SYNC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="SYNC_API_KEY is not configured on the cloud server.",
        )
    if not api_key or api_key != SYNC_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid sync API key.")


@router.post("", response_model=SyncPullResponse)
def sync_with_cloud(
    payload: SyncPushRequest,
    x_sync_api_key: str | None = Header(default=None, alias="X-Sync-API-Key"),
):
    """
    Bi-directional sync initiated by a Raspberry Pi device.

    - Pi sends records modified since last sync
    - Cloud applies them (Last-Write-Wins on updated_at)
    - Cloud returns its own changes since the same timestamp
    """
    _verify_api_key(x_sync_api_key)

    server_time, outbound, apply_stats = run_cloud_sync(
        device_id=payload.device_id,
        device_name=payload.device_name,
        since=payload.since,
        incoming_changes=payload.changes,
    )

    return {
        "server_time": server_time,
        "since": payload.since,
        "changes": outbound,
        "applied": apply_stats,
        "message": "Sync completed successfully.",
    }
