import os
from pathlib import Path
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import init_db

# 1. Check the app role early (defaults to 'pi' if not set)
APP_ROLE = os.getenv("APP_ROLE", "pi")

# 2. Base routers that NEVER use face_recognition/opencv
from app.routers import courses, students, registrations, admin, departments, levels, sync

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _warmup_face_profiles() -> None:
    """Build dlib embeddings for any enrolled students missing face profiles (Skipped on Cloud)."""
    if APP_ROLE == "cloud":
        print("[startup] Skipping face profile warmup (Cloud mode active).")
        return

    try:
        from app.services.face_embeddings import sync_all_missing_embeddings, DLIB_AVAILABLE
        from app.services.attendance_matcher import invalidate_course_cache

        if DLIB_AVAILABLE:
            count = sync_all_missing_embeddings()
            if count:
                invalidate_course_cache()
                print(f"[startup] Built {count} face embedding(s) for attendance matching.")
    except Exception as exc:
        print(f"[startup] Face profile warmup skipped: {exc}")


app = FastAPI(
    title="Facial Recognition Attendance System",
    description="Course admin, student enrollment, and attendance API.",
    version="0.2.0",
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    print("\n--- [VALIDATION ERROR DETAIL] ---")
    print(exc.errors())
    print("---------------------------------\n")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    repaired = init_db()
    if repaired:
        print(f"[startup] Repaired stale FK references on: {', '.join(repaired)}")
    _warmup_face_profiles()


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


# 3. Register lightweight, core routers
app.include_router(departments.router)
app.include_router(levels.router)
app.include_router(courses.router)
app.include_router(students.router)
app.include_router(registrations.router)
app.include_router(admin.router)
app.include_router(sync.router)

# 4. Conditionally register face-heavy routers only if NOT on cloud
if APP_ROLE != "cloud":
    print("[startup] Loading physical face recognition routers...")
    from app.routers import attendance, enrollment
    app.include_router(attendance.router)
    app.include_router(enrollment.router)
else:
    print("[startup] Cloud mode active: Bypassing face recognition & camera routers.")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
