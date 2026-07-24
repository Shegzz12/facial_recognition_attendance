"""
schemas.py — Pydantic models for API request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


# ---------- Departments ----------

class DepartmentCreate(BaseModel):
    name: str = Field(..., examples=["Electrical Engineering"])
    code: Optional[str] = Field(None, examples=["EEE"])


class DepartmentOut(BaseModel):
    id: str
    name: str
    code: Optional[str]
    created_at: str
    updated_at: str


class DepartmentWithLevelsOut(DepartmentOut):
    levels: list["LevelOut"] = []


# ---------- Levels ----------

class LevelCreate(BaseModel):
    department_id: str
    name: str = Field(..., examples=["100 Level"])
    sort_order: int = Field(..., examples=[100])


class LevelOut(BaseModel):
    id: str
    department_id: str
    name: str
    sort_order: int
    created_at: str
    updated_at: str


# ---------- Courses ----------

class CourseCreate(BaseModel):
    department_id: str
    level_id: str
    code: str = Field(..., examples=["EEE101"])
    name: str = Field(..., examples=["Introduction to Electrical Engineering"])
    lecturer: Optional[str] = Field(None, examples=["Dr. Adeyemi"])


class CourseOut(BaseModel):
    id: str
    department_id: str
    level_id: str
    code: str
    name: str
    lecturer: Optional[str]
    created_at: str
    updated_at: str
    department_name: Optional[str] = None
    level_name: Optional[str] = None


# ---------- Students ----------

class StudentCreate(BaseModel):
    matric_no: str = Field(..., examples=["CSC/2021/045"])
    full_name: str = Field(..., examples=["Aisha Bello"])
    department_id: Optional[str] = None
    level_id: Optional[str] = None


class StudentOut(BaseModel):
    id: str
    matric_no: str
    full_name: str
    department_id: Optional[str]
    level_id: Optional[str]
    created_at: str
    updated_at: str


# ---------- Registration ----------

class RegistrationCreate(BaseModel):
    matric_no: str
    course_id: str


class RegistrationOut(BaseModel):
    id: str
    matric_no: str
    course_id: str
    registered_at: str
    created_at: str
    updated_at: str


# ---------- Attendance ----------

class AttendanceMark(BaseModel):
    matric_no: str
    course_id: str
    session_date: str
    source: str = "server"


class AttendanceOut(BaseModel):
    id: str
    matric_no: str
    course_id: str
    session_date: str
    marked_at: str
    source: str
    created_at: str
    updated_at: str


# ---------- Enrollment ----------

class FaceSampleOut(BaseModel):
    id: str
    matric_no: str
    image_path: str
    frame_index: Optional[int] = None
    created_at: str
    updated_at: str


class EnrollmentOut(BaseModel):
    matric_no: str
    full_name: str
    course_ids: list[str]
    courses_registered: list[str]
    face_samples_saved: int
    message: str


# ---------- Admin dashboard ----------

class CourseStatsOut(BaseModel):
    id: str
    code: str
    name: str
    lecturer: Optional[str]
    created_at: str
    updated_at: str
    department_id: str
    department_name: str
    level_id: str
    level_name: str
    student_count: int
    total_attendance_marks: int


class CourseStudentOut(BaseModel):
    matric_no: str
    full_name: str
    registered_at: str
    face_samples: int
    attendance_count: int
    rfid_card_id: Optional[int] = None


# ---------- Attendance scanning ----------

class AttendanceSessionOut(BaseModel):
    course_id: str
    code: str
    name: str
    department_name: str
    level_name: str
    session_date: str
    enrolled_students: int
    students_with_faces: int
    marked_today: int
    dlib_ready: bool


class AttendanceScanOut(BaseModel):
    matched: bool
    marked: bool
    already_marked: bool = False
    matric_no: Optional[str] = None
    full_name: Optional[str] = None
    course_id: str
    session_date: str
    message: str
    distance: Optional[float] = None


# ---------- Sync ----------

class SyncPushRequest(BaseModel):
    device_id: str
    device_name: str
    since: Optional[str] = None
    changes: Dict[str, list[Dict[str, Any]]] = Field(default_factory=dict)


class SyncPullResponse(BaseModel):
    server_time: str
    since: Optional[str] = None
    changes: Dict[str, list[Dict[str, Any]]] = Field(default_factory=dict)
    applied: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    message: str


# ---------- RFID Cards ----------

class RFIDCardCreate(BaseModel):
    matric_no: str
    hex_uid: str


class RFIDCardOut(BaseModel):
    id: str
    card_id: int
    hex_uid: str
    matric_no: str
    created_at: str
    updated_at: str


class RFIDCardRegistrationOut(BaseModel):
    card_id: int
    matric_no: str
    full_name: str
    message: str


DepartmentWithLevelsOut.model_rebuild()
