"""Schémas Pydantic pour les inscriptions."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class EnrollmentCreate(BaseModel):
    student_id: int
    class_id: int
    academic_year_id: int
    fee_variant_id: int | None = None
    notes: str | None = None

    @field_validator("academic_year_id", "student_id", "class_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be a positive integer")
        return v


class EnrollmentUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"prospect", "en_validation", "valide", "rejete", "annule"}
        if v not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")
        return v


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    class_id: int
    academic_year_id: int
    academic_year_name: str
    status: str
    fee_variant_id: int | None
    notes: str | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class EnrollmentListResponse(BaseModel):
    items: list[EnrollmentResponse]
    total: int
    page: int
    size: int
