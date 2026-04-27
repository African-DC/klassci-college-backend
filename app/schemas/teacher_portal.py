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


class TeacherNextCourse(BaseModel):
    """Prochain créneau de cours à venir pour l'enseignant."""

    subject_name: str
    class_name: str
    start_time: str  # "HH:MM"
    end_time: str
    room: str | None = None


class TeacherUpcomingEval(BaseModel):
    """Évaluation à venir (ou récente non saisie) pour le hero du dashboard."""

    id: int
    title: str
    type: str
    date: str  # ISO date YYYY-MM-DD
    class_id: int
    class_name: str
    subject_name: str
    graded_students: int
    total_students: int


class TeacherDashboardStats(BaseModel):
    """Contrat consommé par /teacher/dashboard côté FE.

    Voir `klassci-frontend/lib/contracts/teacher-portal.ts:TeacherDashboardSchema`.
    """

    teacher_name: str
    total_classes: int
    total_students: int
    next_course: TeacherNextCourse | None = None
    upcoming_evaluations: list[TeacherUpcomingEval]
