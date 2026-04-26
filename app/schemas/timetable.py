"""Schémas Pydantic pour l'emploi du temps."""

from pydantic import BaseModel

from app.models.timetable import DayOfWeek

# ---------------------------------------------------------------------------
# Slot CRUD
# ---------------------------------------------------------------------------


class TimetableSlotCreate(BaseModel):
    class_id: int
    teacher_id: int
    subject_id: int
    academic_year_id: int
    day: DayOfWeek
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    room: str | None = None


class TimetableSlotUpdate(BaseModel):
    teacher_id: int | None = None
    subject_id: int | None = None
    day: DayOfWeek | None = None
    start_time: str | None = None
    end_time: str | None = None
    room: str | None = None


class TimetableSlotResponse(BaseModel):
    id: int
    class_id: int
    class_name: str
    teacher_id: int
    teacher_name: str
    subject_id: int
    subject_name: str
    subject_color: str | None = None
    academic_year_id: int
    day: str
    start_time: str
    end_time: str
    room: str | None


# ---------------------------------------------------------------------------
# Teacher availability
# ---------------------------------------------------------------------------


class TeacherAvailabilityCreate(BaseModel):
    day: DayOfWeek
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    available: bool = True
    preferred: bool = False


class TeacherAvailabilityUpdate(BaseModel):
    available: bool | None = None
    preferred: bool | None = None


class TeacherAvailabilityResponse(BaseModel):
    id: int
    teacher_id: int
    day: str
    start_time: str
    end_time: str
    available: bool
    preferred: bool


# ---------------------------------------------------------------------------
# OR-Tools generation
# ---------------------------------------------------------------------------


class AssignmentInput(BaseModel):
    teacher_id: int
    subject_id: int
    hours_per_week: int


class TimeSlotInput(BaseModel):
    day: DayOfWeek
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"


class GenerateTimetableRequest(BaseModel):
    class_id: int
    academic_year_id: int
    assignments: list[AssignmentInput]
    available_slots: list[TimeSlotInput]
    room_id: int | None = None


class GenerateTimetableResponse(BaseModel):
    task_id: str


class TaskStatusResponse(BaseModel):
    status: str  # "pending" | "running" | "success" | "failed"
    result: list[TimetableSlotResponse] | None = None
