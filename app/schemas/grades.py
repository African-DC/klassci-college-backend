"""Schémas Pydantic pour les notes, évaluations et bulletins."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.grade import EvaluationType

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class EvaluationCreate(BaseModel):
    title: str
    type: EvaluationType
    date: date
    coefficient: int = Field(ge=1, le=10)
    subject_id: int
    class_id: int
    academic_year_id: int
    trimester: int = Field(ge=1, le=3)
    # Optional — auto-resolved from current_user when an enseignant crée.
    # Required when an admin/staff délégué crée pour un prof.
    teacher_id: int | None = None


class EvaluationResponse(BaseModel):
    id: int
    title: str
    type: str
    date: date
    coefficient: int
    subject_id: int
    subject_name: str
    class_id: int
    class_name: str
    teacher_id: int
    teacher_name: str
    academic_year_id: int
    trimester: int
    total_students: int
    graded_students: int
    created_at: datetime


class EvaluationListResponse(BaseModel):
    """Enveloppe paginée. `total` porte le compte de l'école, pas de la page."""

    items: list[EvaluationResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Grade
# ---------------------------------------------------------------------------


class GradeResponse(BaseModel):
    student_id: int
    student_name: str
    value: Decimal | None
    status: str


class GradeEntry(BaseModel):
    student_id: int
    value: float | None = Field(None, ge=0, le=20)
    # Élève absent le jour de l'épreuve : zéro d'office. Distinct d'une case
    # laissée vide, qui signifie seulement « pas encore corrigé ». C'est ce
    # marquage qui permet ensuite un billet d'annulation de zéro.
    absent: bool = False


class GradeBatchUpdate(BaseModel):
    grades: list[GradeEntry]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class StudentSummary(BaseModel):
    student_id: int
    student_name: str
    average: Decimal | None
    rank: int | None
    mention: str | None


class SubjectSummary(BaseModel):
    subject_id: int
    subject_name: str
    class_average: Decimal | None


class GradesSummaryResponse(BaseModel):
    class_id: int
    trimester: int
    students: list[StudentSummary]
    subjects: list[SubjectSummary]
