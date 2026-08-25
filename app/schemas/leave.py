"""Schémas des demandes de congé."""

from datetime import date, datetime

from pydantic import BaseModel, field_validator, model_validator

from app.models.leave import LeaveType

_VALID_TYPES = {t.value for t in LeaveType}


class LeaveRequestCreate(BaseModel):
    leave_type: str
    start_date: date
    end_date: date
    reason: str | None = None

    @field_validator("leave_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"Type de congé invalide. Valeurs : {', '.join(sorted(_VALID_TYPES))}")
        return v

    @model_validator(mode="after")
    def _check_dates(self) -> "LeaveRequestCreate":
        if self.end_date < self.start_date:
            raise ValueError("La date de fin doit être postérieure ou égale à la date de début")
        return self


class LeaveReviewRequest(BaseModel):
    comment: str | None = None


class LeaveInterimAssign(BaseModel):
    teacher_id: int | None = None


class LeaveRequestResponse(BaseModel):
    id: int
    user_id: int
    leave_type: str
    start_date: date
    end_date: date
    reason: str | None = None
    status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    review_comment: str | None = None
    interim_teacher_id: int | None = None
    interim_teacher_name: str | None = None
    created_at: datetime
    requester_name: str | None = None
    requester_role: str | None = None
