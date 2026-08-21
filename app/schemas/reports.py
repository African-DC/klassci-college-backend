"""Schémas Pydantic pour les bulletins scolaires (reports)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class BulletinGenerateRequest(BaseModel):
    class_id: int
    trimester: int = Field(ge=1, le=3)
    academic_year_id: int


# ---------------------------------------------------------------------------
# Response — Subject Average
# ---------------------------------------------------------------------------


class SubjectAverageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    subject_id: int
    subject_name: str
    average: Decimal
    coefficient: int


# ---------------------------------------------------------------------------
# Response — Bulletin
# ---------------------------------------------------------------------------


class BulletinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    student_name: str
    student_photo_url: str | None = None
    student_enrollment_number: str | None = None
    class_id: int
    class_name: str
    academic_year_id: int
    trimester: int
    average: Decimal | None
    rank: int | None
    total_students: int
    mention: str | None
    teacher_comment: str | None
    council_decision: str | None
    file_url: str | None
    generated_at: datetime | None
    is_published: bool
    subject_averages: list[SubjectAverageResponse]
    created_at: datetime
    updated_at: datetime


class BulletinListResponse(BaseModel):
    """Enveloppe paginée. `total` porte le compte de l'école, pas de la page."""

    items: list[BulletinResponse]
    total: int
    page: int
    size: int


class BulletinGenerateResponse(BaseModel):
    message: str
    generated: int
    bulletins: list[BulletinResponse]
