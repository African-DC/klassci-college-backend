"""Schemas Pydantic pour le portail eleve (read-only)."""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Grades
# ---------------------------------------------------------------------------


class EvaluationDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    type: str
    date: date
    coefficient: int
    trimester: int
    subject_name: str


class StudentGradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    value: Decimal | None
    status: str
    evaluation: EvaluationDetail


class StudentGradesListResponse(BaseModel):
    items: list[StudentGradeResponse]
    total: int


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------


class TimetableSlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    day: str
    start_time: time
    end_time: time
    subject_name: str
    teacher_name: str
    room_name: str | None


class StudentTimetableResponse(BaseModel):
    class_name: str
    slots: list[TimetableSlotResponse]


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: Decimal
    method: str
    status: str
    reference: str | None
    created_at: datetime


class EnrollmentFeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_name: str
    amount: Decimal
    status: str
    payments: list[PaymentResponse]


class StudentFeesResponse(BaseModel):
    total_due: Decimal
    total_paid: Decimal
    balance: Decimal
    fees: list[EnrollmentFeeResponse]


# ---------------------------------------------------------------------------
# Bulletins
# ---------------------------------------------------------------------------


class BulletinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trimester: int
    average: Decimal | None
    rank: int | None
    mention: str | None
    class_name: str
    academic_year_name: str
    file_url: str | None
    generated_at: datetime | None

    # Retenue pour impayé. Quand elle est active, les champs de contenu
    # ci-dessus valent `None` : le bulletin est annoncé, pas divulgué.
    is_withheld: bool = False
    withheld_reason: str | None = None
    withheld_amount: float | None = None


class StudentBulletinsListResponse(BaseModel):
    items: list[BulletinResponse]
    total: int


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


class StudentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    birth_date: date | None
    birth_place: str | None = None
    genre: str | None
    enrollment_number: str | None
    email: str | None
    class_name: str | None
    class_id: int | None
    enrollment_status: str | None
    academic_year_name: str | None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class StudentNextCourse(BaseModel):
    """Prochain créneau dans la semaine pour l'élève."""

    subject_name: str
    teacher_name: str
    start_time: str  # HH:MM
    end_time: str
    room: str | None = None


class StudentLatestGrade(BaseModel):
    """Dernière note saisie de l'élève (mise en avant sur le tableau de bord)."""

    value: float
    out_of: int = 20
    subject_name: str
    evaluation_title: str
    type: str
    trimester: int
    date: date


class StudentDashboardResponse(BaseModel):
    """Contrat consommé par /student/dashboard côté FE.

    Voir `klassci-frontend/lib/contracts/student-portal.ts:StudentDashboardSchema`.
    """

    student_name: str
    class_name: str
    next_course: StudentNextCourse | None = None
    general_average: float | None = None
    latest_grade: StudentLatestGrade | None = None
    fees_remaining: float
    total_absences: int
    current_academic_year: str | None = None
