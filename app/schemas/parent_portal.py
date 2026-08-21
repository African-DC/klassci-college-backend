"""Schémas Pydantic pour le portail parent."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Children
# ---------------------------------------------------------------------------


class ChildEnrollmentInfo(BaseModel):
    """Résumé de l'inscription active d'un enfant."""

    model_config = ConfigDict(from_attributes=True)

    enrollment_id: int
    class_id: int
    class_name: str
    academic_year_name: str
    status: str


class ChildResponse(BaseModel):
    """Enfant vu par le parent."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    birth_place: str | None = None
    enrollment_number: str | None
    relationship_type: str
    enrollment: ChildEnrollmentInfo | None = None


class ChildrenListResponse(BaseModel):
    children: list[ChildResponse]


# ---------------------------------------------------------------------------
# Dashboard (résumé global parent)
# ---------------------------------------------------------------------------


class ParentDashboardChild(BaseModel):
    """Résumé KPIs d'un enfant pour la dashboard parent."""

    id: int
    full_name: str
    class_name: str
    general_average: float | None
    total_absences: int
    # Float (not Decimal) so the JSON encoder emits a number, not a string.
    # The FE Zod schema validates as z.number() — Pydantic's default
    # Decimal→str serialization breaks the contract. Acceptable precision
    # loss because we display thousands of XOF, not micropayments.
    fees_remaining: float


class ParentDashboardResponse(BaseModel):
    """Dashboard parent — agrège les KPIs des enfants liés."""

    parent_name: str
    total_children: int
    children: list[ParentDashboardChild]
    current_academic_year: str | None = None


# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


class GradeDetail(BaseModel):
    """Note d'un enfant pour une évaluation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    value: Decimal | None
    status: str
    evaluation_title: str
    evaluation_type: str
    evaluation_date: date
    subject_name: str
    coefficient: int
    trimester: int


class ChildGradesResponse(BaseModel):
    student_id: int
    grades: list[GradeDetail]


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


class PaymentDetail(BaseModel):
    """Détail d'un paiement."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    method: str
    status: str
    reference: str | None
    created_at: datetime


class FeeDetail(BaseModel):
    """Frais d'inscription avec paiements."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    status: str
    category_name: str
    payments: list[PaymentDetail]


class ChildFeesResponse(BaseModel):
    student_id: int
    enrollment_id: int | None
    fees: list[FeeDetail]
    total_due: Decimal
    total_paid: Decimal


# ---------------------------------------------------------------------------
# Bulletins
# ---------------------------------------------------------------------------


class BulletinDetail(BaseModel):
    """Bulletin trimestriel d'un enfant."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    trimester: int
    average: Decimal | None
    rank: int | None
    mention: str | None
    class_name: str
    academic_year_name: str
    is_published: bool
    generated_at: datetime | None

    # Retenue pour impayé. Quand elle est active, moyenne, rang et mention
    # valent `None` : le bulletin est annoncé, pas divulgué.
    is_withheld: bool = False
    withheld_reason: str | None = None
    withheld_amount: float | None = None


class ChildBulletinsResponse(BaseModel):
    student_id: int
    bulletins: list[BulletinDetail]


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------


class ChildTimetableSlot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day: str
    start_time: str
    end_time: str
    subject_name: str
    teacher_name: str
    room_name: str | None


class ChildTimetableResponse(BaseModel):
    student_id: int
    class_name: str
    slots: list[ChildTimetableSlot]
