# Raspberry Pi Deployment Guide

This guide explains how to deploy the facial recognition attendance system on a Raspberry Pi with bi-directional sync to a cloud instance.

## Prerequisites

- Raspberry Pi 4 (recommended) with Raspberry Pi OS
- Python 3.9+
- Internet connection for sync
- Camera module (for face recognition)

## Step 1: Prepare the Raspberry Pi

### Update the system
```bash
sudo apt update && sudo apt upgrade -y
```

### Install system dependencies
```bash
# Install Python and pip
sudo apt install python3 python3-pip python3-venv -y

# Install OpenCV dependencies
sudo apt install libopencv-dev python3-opencv -y

# Install dlib dependencies (for face recognition)
sudo apt install cmake build-essential libopenblas-dev liblapack-dev \
    libx11-dev libgtk-3-dev -y

# Install camera dependencies
sudo apt install libcamera-tools libcamera0 -y
```

## Step 2: Deploy the Application

### Copy files to the Pi
Copy the entire project directory to your Raspberry Pi:

```bash
# On your local machine, run:
scp -r facial_recognition_based_attendance/ pi@your-pi-ip:~/
```

### Set up Python environment
```bash
# SSH into the Pi
ssh pi@your-pi-ip

# Navigate to the project
cd ~/facial_recognition_based_attendance

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configure environment
```bash
# Copy the example environment file
cp .env.pi.example .env

# Edit the configuration
nano .env
```

Update these values in `.env`:
- `SYNC_CLOUD_URL`: Your cloud server URL (e.g., https://attendance.yourdomain.com)
- `SYNC_API_KEY`: A secure random key (must match cloud server)
- `SYNC_DEVICE_ID`: Unique identifier for this Pi (e.g., pi-lab-01)
- `SYNC_DEVICE_NAME`: Human-readable name (e.g., Raspberry Pi Lab 01)
- `SYNC_INTERVAL_SECONDS`: How often to sync (default: 300 = 5 minutes)

## Step 3: Initialize the Database

```bash
# Run the database initialization
python -m app.database
```

This will:
- Create the SQLite database with UUID schema
- Set up sync tables
- Prepare the database for bi-directional sync

## Step 4: Run the Application

### Option A: Run manually (for testing)
```bash
# Activate virtual environment
source venv/bin/activate

# Run the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Option B: Run with sync agent (recommended)
```bash
# Activate virtual environment
source venv/bin/activate

# Start the sync agent in background
python scripts/sync_agent.py --loop &

# Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Option C: Run as a system service (production)
Create a systemd service file:

```bash
sudo nano /etc/systemd/system/attendance.service
```

Add this content:
```ini
[Unit]
Description=Facial Recognition Attendance System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/facial_recognition_based_attendance
Environment="PATH=/home/pi/facial_recognition_based_attendance/venv/bin"
ExecStart=/home/pi/facial_recognition_based_attendance/venv/bin/python scripts/sync_agent.py --loop
Restart=always

[Install]
WantedBy=multi-user.target
```

Create another service for the web server:
```bash
sudo nano /etc/systemd/system/attendance-web.service
```

Add this content:
```ini
[Unit]
Description=Attendance Web Server
After=network.target attendance.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/facial_recognition_based_attendance
Environment="PATH=/home/pi/facial_recognition_based_attendance/venv/bin"
ExecStart=/home/pi/facial_recognition_based_attendance/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable attendance.service attendance-web.service
sudo systemctl start attendance.service attendance-web.service
```

Check status:
```bash
sudo systemctl status attendance.service
sudo systemctl status attendance-web.service
```

## Step 5: Cloud Server Setup

On your cloud server, follow similar steps but use the cloud configuration:

```bash
# Copy the example environment file
cp .env.cloud.example .env

# Edit the configuration
nano .env
```

Update these values in `.env`:
- `SYNC_API_KEY`: The same secure key used on the Pi
- `APP_ROLE`: Should be set to `cloud`

The cloud server will automatically:
- Accept sync requests from registered Pi devices
- Apply changes using Last-Write-Wins conflict resolution
- Return changes to the Pi for local application

## Sync Architecture

### How Sync Works

1. **Pi Initiated**: The Raspberry Pi initiates sync by calling the cloud's `/sync` endpoint
2. **Bi-directional Exchange**: 
   - Pi sends changes made since last sync
   - Cloud applies these changes to its database
   - Cloud returns its own changes since the same timestamp
   - Pi applies cloud changes to its local database
3. **Conflict Resolution**: Uses Last-Write-Wins based on `updated_at` timestamps
4. **Soft Deletes**: Deleted records are synced via `is_deleted` flag

### Synced Tables

The following tables are synced between Pi and Cloud:
- departments
- levels
- courses
- students
- course_registrations
- face_samples (with base64-encoded images)
- face_embeddings (with base64-encoded vectors)
- attendance_logs

### Data Flow

```
Pi (Local)                    Cloud (Remote)
    |                              |
    | -- POST /sync -------------> |
    |    {changes, since}         |
    |                              |
    | <--- {changes, server} ---- |
    |                              |
    | Apply remote changes         |
    |                              |
```

## Testing the Sync

### Manual sync test
```bash
# On the Pi, run a single sync
python scripts/sync_agent.py
```

### Verify sync status
Check the sync logs in the application output or systemd journal:
```bash
sudo journalctl -u attendance.service -f
```

## Troubleshooting

### Sync fails with API key error
- Ensure `SYNC_API_KEY` matches on both Pi and cloud
- Check that the cloud server is accessible from the Pi

### Database migration issues
- If you have an old database with integer IDs, the migration will run automatically
- Backup your database before migration: `cp attendance.db attendance.db.backup`

### Face recognition not working on Pi
- Ensure dlib and face-recognition are installed: `pip install face-recognition`
- Check camera permissions: `sudo usermod -a -G video pi`
- Reboot after adding user to video group

### Performance issues on Pi
- Reduce sync interval in `.env` (e.g., `SYNC_INTERVAL_SECONDS=600`)
- Use a smaller face sample size during enrollment
- Consider using a Raspberry Pi 4 with more RAM

## Security Considerations

1. **API Key**: Use a strong, random `SYNC_API_KEY` (at least 32 characters)
2. **HTTPS**: Use HTTPS for the cloud server URL
3. **Firewall**: Configure firewall to only allow necessary ports
4. **Database**: The SQLite database should be backed up regularly

## Backup Strategy

### Backup Pi database
```bash
# Create backup
cp attendance.db attendance.db.backup.$(date +%Y%m%d)

# Sync backup to cloud (optional)
scp attendance.db.backup.* user@cloud-server:/backups/
```

### Backup cloud database
```bash
# Create backup
cp attendance.db attendance.db.backup.$(date +%Y%m%d)
```

## Monitoring

### Check sync status
The sync agent logs each sync operation:
```
[sync OK] 2024-01-15T10:30:00+00:00 | pushed=['departments', 'students'] pulled=['attendance_logs']
```

### Monitor database size
```bash
ls -lh attendance.db
```

### Monitor disk space
```bash
df -h
```

## File Structure for Pi Deployment

```
facial_recognition_based_attendance/
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── db_helpers.py
│   ├── main.py
│   ├── migrations/
│   │   └── uuid_schema.py
│   ├── routers/
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
│   │   ├── attendance_matcher.py
│   │   ├── face_embeddings.py
│   │   └── face_extractor.py
│   └── sync/
│       ├── __init__.py
│       ├── constants.py
│       └── engine.py
├── scripts/
│   ├── sync_agent.py
│   ├── inspect_db.py
│   └── repair_db.py
├── static/
│   └── (web interface files)
├── uploads/
│   └── faces/
│       └── (student face images)
├── attendance.db
├── requirements.txt
├── .env (created from .env.pi.example)
└── venv/ (created during setup)
```

## Next Steps

1. Deploy the cloud server following the cloud configuration
2. Set up the first Raspberry Pi using this guide
3. Test the sync between Pi and cloud
4. Deploy additional Pis as needed (each with unique `SYNC_DEVICE_ID`)
5. Set up monitoring and backups
