"""Schemas Pydantic pour le portail enseignant (read-only)."""

from datetime import time

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


class TeacherClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    class_id: int
    class_name: str
    level_name: str
    subject_name: str
    student_count: int


class TeacherClassesListResponse(BaseModel):
    items: list[TeacherClassResponse]
    total: int


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


class TeacherScheduleSlot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day: str
    start_time: time
    end_time: time
    subject_name: str
    class_name: str
    room_name: str | None


class TeacherScheduleResponse(BaseModel):
    items: list[TeacherScheduleSlot]
    total: int


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------


class ClassAverageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    class_id: int
    class_name: str
    subject_name: str
    average: float | None


class TeacherDashboardStats(BaseModel):
    total_classes: int
    total_students: int
    upcoming_evaluations: int
    class_averages: list[ClassAverageItem]
