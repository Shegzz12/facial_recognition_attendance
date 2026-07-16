# Deployment Checklist

## What to Move to Raspberry Pi

Copy the entire project directory to your Raspberry Pi. The sync infrastructure is already built into the codebase.

### Required Files and Directories

```
facial_recognition_based_attendance/
├── app/                          # Main application code
│   ├── __init__.py
│   ├── config.py                 # Environment configuration
│   ├── database.py              # Database connection and UUID migration
│   ├── db_helpers.py            # UUID and timestamp helpers
│   ├── main.py                  # FastAPI application entry point
│   ├── migrations/
│   │   └── uuid_schema.py       # UUID schema definition
│   ├── routers/                 # API endpoints
│   │   ├── admin.py
│   │   ├── attendance.py
│   │   ├── courses.py
│   │   ├── departments.py
│   │   ├── enrollment.py
│   │   ├── levels.py
│   │   ├── registrations.py
│   │   ├── students.py
│   │   └── sync.py              # Sync endpoint (already exists)
│   ├── schemas.py               # Pydantic models (updated for UUIDs)
│   ├── services/
│   │   ├── attendance_matcher.py
│   │   ├── face_embeddings.py
│   │   └── face_extractor.py
│   └── sync/                    # Sync engine (already exists)
│       ├── __init__.py
│       ├── constants.py
│       └── engine.py
├── scripts/                     # Utility scripts
│   ├── sync_agent.py            # Pi sync agent (already exists)
│   ├── inspect_db.py
│   └── repair_db.py
├── static/                      # Web interface files
├── uploads/                     # Will be created for face images
│   └── faces/
├── requirements.txt             # Python dependencies
├── .env.pi.example             # Pi configuration template
├── .env.cloud.example          # Cloud configuration template
├── PI_DEPLOYMENT.md            # Deployment guide
└── DEPLOYMENT_CHECKLIST.md     # This file
```

## Pre-Deployment Steps (Current Machine)

### 1. Test UUID Migration
```bash
# Run the database migration to ensure it works
python -m app.database
```

### 2. Verify Sync Infrastructure
The sync infrastructure is already in place:
- ✅ Sync endpoint: `app/routers/sync.py`
- ✅ Sync engine: `app/sync/engine.py`
- ✅ Sync agent: `scripts/sync_agent.py`
- ✅ Sync constants: `app/sync/constants.py`

### 3. Test Current Application
```bash
# Start the server
uvicorn app.main:app --reload

# Test the API endpoints
# - Create departments, levels, courses
# - Register students
# - Mark attendance
```

## Cloud Server Deployment

### 1. Deploy to Cloud
- Copy the entire project to your cloud server
- Use `.env.cloud.example` as template for `.env`
- Set `APP_ROLE=cloud`
- Set `SYNC_API_KEY` to a secure random string

### 2. Initialize Cloud Database
```bash
python -m app.database
```

### 3. Start Cloud Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Raspberry Pi Deployment

### 1. Copy Files to Pi
```bash
scp -r facial_recognition_based_attendance/ pi@your-pi-ip:~/
```

### 2. Set Up Pi Environment
```bash
# SSH into Pi
ssh pi@your-pi-ip

# Navigate to project
cd ~/facial_recognition_based_attendance

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Pi
```bash
# Copy environment template
cp .env.pi.example .env

# Edit configuration
nano .env
```

Set these values:
- `APP_ROLE=pi`
- `SYNC_CLOUD_URL=https://your-cloud-server.com`
- `SYNC_API_KEY=same-as-cloud`
- `SYNC_DEVICE_ID=pi-lab-01`
- `SYNC_DEVICE_NAME=Raspberry Pi Lab 01`

### 4. Initialize Pi Database
```bash
python -m app.database
```

### 5. Start Pi Services

#### Option A: Manual (for testing)
```bash
# Terminal 1: Start sync agent
python scripts/sync_agent.py --loop

# Terminal 2: Start web server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### Option B: Systemd Service (production)
Follow the instructions in `PI_DEPLOYMENT.md` to create systemd services.

## Testing the Sync

### 1. Test Cloud Server
```bash
# On cloud server, test sync endpoint is available
curl http://localhost:8000/docs
# Look for /sync endpoint in the API documentation
```

### 2. Test Pi Sync
```bash
# On Pi, run a single sync
python scripts/sync_agent.py
```

Expected output:
```
Sync completed:
  since: None
  server_time: 2024-01-15T10:30:00+00:00
  pushed_tables: []
  pulled_tables: ['departments', 'courses', 'students']
  local_apply_stats: {...}
  cloud_apply_stats: {...}
```

### 3. Test Bi-directional Sync

#### On Cloud:
1. Create a department via API
2. Create a course
3. Register a student

#### On Pi:
1. Run sync: `python scripts/sync_agent.py`
2. Verify data appears in Pi database
3. Mark attendance for a student

#### On Cloud:
1. Run sync (or wait for Pi to push)
2. Verify attendance appears in cloud database

## Key Changes Made for Sync

### Database Schema
- ✅ All primary keys changed from INTEGER to TEXT (UUID)
- ✅ Added `created_at` and `updated_at` timestamps to all tables
- ✅ Added `is_deleted` soft-delete flag to all tables
- ✅ Added sync tables: `sync_local_state`, `sync_devices`

### API Schemas
- ✅ All ID fields changed from int to str (UUID)
- ✅ Added `updated_at` to response models
- ✅ Added sync schemas: `SyncPushRequest`, `SyncPullResponse`

### Routers
- ✅ Updated all routers to use UUID IDs
- ✅ Added soft-delete queries (WHERE is_deleted = 0)
- ✅ Updated INSERT statements to include UUID, timestamps
- ✅ Added sync router to main.py

### Services
- ✅ Updated attendance_matcher to use UUID course_id
- ✅ Added soft-delete checks to queries

## Sync Configuration

### Environment Variables

**Cloud Server (.env):**
```
APP_ROLE=cloud
SYNC_API_KEY=your-secure-random-key
```

**Raspberry Pi (.env):**
```
APP_ROLE=pi
SYNC_CLOUD_URL=https://your-cloud-server.com
SYNC_API_KEY=same-as-cloud
SYNC_DEVICE_ID=pi-lab-01
SYNC_DEVICE_NAME=Raspberry Pi Lab 01
SYNC_INTERVAL_SECONDS=300
```

### Sync Behavior

- **Interval**: Every 5 minutes (configurable)
- **Initiation**: Pi initiates sync by calling cloud `/sync` endpoint
- **Conflict Resolution**: Last-Write-Wins based on `updated_at` timestamp
- **Soft Deletes**: Deleted records synced via `is_deleted` flag
- **Data Types**: 
  - Text data: JSON
  - BLOB data (face embeddings): Base64 encoded
  - File data (face images): Base64 encoded

## Troubleshooting

### Sync fails with 401 Unauthorized
- Check that `SYNC_API_KEY` matches on both Pi and cloud
- Verify the cloud server is accessible from Pi

### Database migration issues
- The migration runs automatically on first run
- If you have existing data, it will be migrated to UUID schema
- Backup your database before: `cp attendance.db attendance.db.backup`

### UUIDs not working
- Ensure you've run `python -m app.database` on both cloud and Pi
- Check that the database schema uses TEXT primary keys

### Soft deletes not syncing
- Verify that all queries include `AND is_deleted = 0`
- Check that deletions use `soft_delete()` function instead of DELETE

## Security Notes

1. **API Key**: Use a strong, random `SYNC_API_KEY` (minimum 32 characters)
2. **HTTPS**: Always use HTTPS for `SYNC_CLOUD_URL` in production
3. **Firewall**: Configure firewall to only allow necessary ports
4. **Backups**: Regularly backup both cloud and Pi databases

## Performance Considerations

### For Raspberry Pi:
- Reduce sync interval if needed (e.g., 600 seconds = 10 minutes)
- Use smaller face sample sizes during enrollment
- Consider Pi 4 with 4GB+ RAM for better performance

### For Cloud:
- Use a hosting provider with good uptime
- Implement database backups
- Monitor sync logs for errors

## Next Steps After Deployment

1. **Monitor**: Check sync logs regularly
2. **Backup**: Set up automated database backups
3. **Scale**: Add more Pis as needed (each with unique `SYNC_DEVICE_ID`)
4. **Optimize**: Adjust sync interval based on usage patterns
