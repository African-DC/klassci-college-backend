"""Schemas Pydantic pour le pointage enseignant (Phase 7b).

Endpoints couverts :
- POST /admin/teachers/{id}/attendance (admin/staff saisit, validé direct)
- POST /teacher/attendance/self-declare (prof se déclare, en attente)
- PATCH /admin/teacher-attendance/{id}/validate (admin valide auto-décl)
- GET /admin/teachers/{id}/attendance (liste filtrée)
- GET /admin/teachers/{id}/attendance/stats (KPIs)
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TeacherAttendanceStatusLiteral = Literal[
    "present",
    "absent_excused",
    "absent_unexcused",
    "late",
]


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class TeacherAttendanceCreate(BaseModel):
    """Saisie d'un pointage par admin/staff.

    `slot_id` optionnel : permet de noter une absence hors EDT (réunion DREN,
    congé maladie sans slot précis). Si fourni, doit appartenir au teacher.

    `late_minutes` ignoré si `status != "late"`.
    """

    slot_id: int | None = None
    date: date_type
    status: TeacherAttendanceStatusLiteral
    late_minutes: int = Field(default=0, ge=0, le=480)  # max 8h = 480min
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("late_minutes")
    @classmethod
    def normalize_late_minutes(cls, v: int, info) -> int:  # type: ignore[no-untyped-def]
        status = info.data.get("status")
        if status != "late":
            return 0
        return v


class TeacherSelfDeclareCreate(BaseModel):
    """Auto-déclaration par le prof — toujours en attente de validation admin.

    Le `teacher_id` est résolu depuis le JWT (current user). On laisse
    juste les champs métier.
    """

    slot_id: int | None = None
    date: date_type
    status: TeacherAttendanceStatusLiteral
    late_minutes: int = Field(default=0, ge=0, le=480)
    notes: str | None = Field(default=None, max_length=1000)


class TeacherAttendanceValidate(BaseModel):
    """Validation admin d'une auto-déclaration.

    `approved=False` rejette : on conserve la row pour audit mais
    `is_validated` reste False + `validated_by` rempli.
    """

    approved: bool = True
    admin_notes: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


class TeacherAttendanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    teacher_id: int
    teacher_full_name: str
    slot_id: int | None
    slot_summary: str | None  # ex: "Lundi 10h-11h Maths 6ème B" (composé service)
    date: date_type
    academic_year_id: int
    status: TeacherAttendanceStatusLiteral
    late_minutes: int
    notes: str | None

    declared_by_user_id: int
    declared_by_email: str | None
    declared_at: datetime
    is_validated: bool
    validated_by_user_id: int | None
    validated_by_email: str | None
    validated_at: datetime | None

    created_at: datetime
    updated_at: datetime


class TeacherAttendanceListResponse(BaseModel):
    items: list[TeacherAttendanceResponse]
    total: int


class TeacherAttendanceStats(BaseModel):
    """KPIs agrégés pour la fiche teacher 360° tab Présences."""

    teacher_id: int
    academic_year_id: int
    academic_year_name: str

    total_sessions: int  # = slots EDT du teacher pour l'AY (théorique)
    sessions_present: int
    sessions_absent_excused: int
    sessions_absent_unexcused: int
    sessions_late: int

    attendance_rate: float  # 0-100, présent / total
    total_late_minutes: int
    avg_late_minutes_when_late: float  # 0 si jamais en retard

    pending_validation_count: int  # auto-déclarations en attente admin
