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
    genre: str | None
    enrollment_number: str | None
    email: str | None
    class_name: str | None
    class_id: int | None
    enrollment_status: str | None
    academic_year_name: str | None
