# Facial Recognition Attendance System - Pi Ready Package

## Quick Start on Raspberry Pi

### 1. Copy to Pi
Copy the entire `pi-ready-package` folder to your Pi via USB flash drive or SCP.

### 2. Set Up Environment
```bash
cd ~/pi-ready-package
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure
```bash
cp .env.pi.example .env
nano .env
```

Edit these values:
- `SYNC_CLOUD_URL`: Your cloud server URL (if syncing)
- `SYNC_API_KEY`: Secure random key (must match cloud)
- `SYNC_DEVICE_ID`: Unique ID for this Pi (e.g., pi-lab-01)
- `SYNC_DEVICE_NAME`: Human-readable name

### 4. Initialize Database
```bash
python -m app.database
```

### 5. Run the Server
```bash
# Option 1: Manual (for testing)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Option 2: With sync agent (recommended)
python scripts/sync_agent.py --loop &
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6. Access the Interface
Open your browser to: `http://pi-ip-address:8000/static/index.html`

## What's Fixed in This Package

### Backend Fixes
- ✅ UUID migration for all tables (departments, levels, courses, students, etc.)
- ✅ Soft-delete support (is_deleted flag)
- ✅ Timestamps for conflict resolution (created_at, updated_at)
- ✅ Sync infrastructure for bi-directional cloud sync
- ✅ Fixed enrollment.py import error (removed legacy function)

### Frontend Fixes
- ✅ Fixed department ID field name (department_id → id) in admin.js, index.js, attendance-setup.js
- ✅ Fixed level ID field name (level_id → id) in admin.js, index.js, attendance-setup.js
- ✅ Fixed course ID field name (course_id → id) in admin.js, attendance-setup.js, register.js
- ✅ Removed Number() conversion for UUID IDs in course creation
- ✅ Fixed course card rendering and student view
- ✅ Fixed attendance-setup.js and register.js ID handling

## File Structure

```
pi-ready-package/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── db_helpers.py
│   ├── main.py
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── uuid_schema.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── attendance.py
│   │   ├── courses.py
│   │   ├── departments.py
│   │   ├── enrollment.py
│   │   ├── levels.py
│   │   ├── registrations.py
│   │   ├── students.py
│   │   └── sync.py
│   ├── schemas.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── attendance_matcher.py
│   │   ├── face_embeddings.py
│   │   └── face_extractor.py
│   └── sync/
│       ├── __init__.py
│       ├── constants.py
│       └── engine.py
├── scripts/
│   ├── __init__.py
│   └── sync_agent.py
├── static/
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   ├── admin.js          # FIXED
│   │   ├── index.js          # FIXED
│   │   ├── attendance.js     # FIXED
│   │   ├── attendance-setup.js  # FIXED
│   │   └── register.js       # FIXED
│   ├── admin.html
│   ├── attendance-setup.html
│   ├── attendance.html
│   ├── index.html
│   └── register.html
├── uploads/
│   └── faces/ (created automatically)
├── requirements.txt
├── .env.pi.example
├── .env.cloud.example
└── README_PI.md
```

## System Requirements

- Raspberry Pi 4 (recommended) with 4GB+ RAM
- Raspberry Pi OS (64-bit recommended)
- Python 3.9+
- Camera module (for face recognition)
- Internet connection (for cloud sync)

## Optional: Install as System Service

For automatic startup on boot:

```bash
sudo nano /etc/systemd/system/attendance.service
```

Add:
```ini
[Unit]
Description=Attendance Sync Agent
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/pi-ready-package
Environment="PATH=/home/pi/pi-ready-package/venv/bin"
ExecStart=/home/pi/pi-ready-package/venv/bin/python scripts/sync_agent.py --loop
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo nano /etc/systemd/system/attendance-web.service
```

Add:
```ini
[Unit]
Description=Attendance Web Server
After=network.target attendance.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/pi-ready-package
Environment="PATH=/home/pi/pi-ready-package/venv/bin"
ExecStart=/home/pi/pi-ready-package/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable attendance.service attendance-web.service
sudo systemctl start attendance.service attendance-web.service
```

## Troubleshooting

### Server won't start
- Check that Python 3.9+ is installed: `python3 --version`
- Ensure virtual environment is activated: `source venv/bin/activate`
- Check database initialization: `python -m app.database`

### Face recognition not working
- Install face-recognition: `pip install face-recognition`
- Check camera permissions: `sudo usermod -a -G video pi`
- Reboot after adding user to video group

### Sync not working
- Verify SYNC_API_KEY matches on cloud and Pi
- Check cloud server is accessible from Pi
- Review sync agent logs

## Support

For issues or questions, refer to the original project documentation or check the API docs at `http://pi-ip:8000/docs`
