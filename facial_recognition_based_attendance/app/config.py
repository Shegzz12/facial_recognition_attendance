"""
Runtime configuration via environment variables.

Cloud server (.env):
  APP_ROLE=cloud
  SYNC_API_KEY=your-long-random-secret

Raspberry Pi (.env):
  APP_ROLE=pi
  SYNC_CLOUD_URL=https://your-cloud-server.com
  SYNC_API_KEY=same-secret-as-cloud
  SYNC_DEVICE_ID=pi-lab-01
  SYNC_DEVICE_NAME=Raspberry Pi Lab
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

APP_ROLE: str = os.getenv("APP_ROLE", "cloud")  # cloud | pi
SYNC_API_KEY: str = os.getenv("SYNC_API_KEY", "")
SYNC_CLOUD_URL: str = os.getenv("SYNC_CLOUD_URL", "").rstrip("/")
SYNC_DEVICE_ID: str = os.getenv("SYNC_DEVICE_ID", "pi-001")
SYNC_DEVICE_NAME: str = os.getenv("SYNC_DEVICE_NAME", "Raspberry Pi")
SYNC_INTERVAL_SECONDS: int = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))

IS_CLOUD: bool = APP_ROLE == "cloud"
IS_PI: bool = APP_ROLE == "pi"
