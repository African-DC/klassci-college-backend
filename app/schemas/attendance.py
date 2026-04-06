"""Schemas Pydantic pour les presences."""

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, field_validator


class AttendanceRecordInput(BaseModel):
    """Single student attendance record in a session."""

    student_id: int
    status: str  # present, absent, late, excused
    time_in: time | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        allowed = {"present", "absent", "late", "excused"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v

    @field_validator("student_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class SessionCreate(BaseModel):
    """Create attendance session with records for all students."""

    entity_type: str  # "class" or "exam"
    context_id: int  # class_id or exam_id
    date: date
    academic_year_id: int
    records: list[AttendanceRecordInput]

    @field_validator("entity_type")
    @classmethod
    def valid_entity_type(cls, v: str) -> str:
        allowed = {"class", "exam"}
        if v not in allowed:
            raise ValueError(f"entity_type must be one of {sorted(allowed)}")
        return v

    @field_validator("context_id", "academic_year_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class SessionUpdate(BaseModel):
    """Update attendance records in a session."""

    records: list[AttendanceRecordInput]


class AttendanceRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    status: str
    time_in: time | None
    time_out: time | None
    source: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entity_type: str
    context_id: int
    date: date
    academic_year_id: int
    records: list[AttendanceRecordResponse]
    created_at: datetime
    updated_at: datetime


class StudentAttendanceResponse(BaseModel):
    """Paginated attendance history for a student."""

    items: list[AttendanceRecordResponse]
    total: int
    page: int
    size: int


class StudentAttendanceSummary(BaseModel):
    student_id: int
    first_name: str
    last_name: str
    present_count: int
    absent_count: int
    late_count: int
    excused_count: int
    attendance_rate: float


class ClassAttendanceStats(BaseModel):
    """Stats for a class: attendance rate, absences per student."""

    class_id: int
    total_sessions: int
    attendance_rate: float  # percentage
    students: list[StudentAttendanceSummary]
