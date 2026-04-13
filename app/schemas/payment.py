"""Schémas Pydantic pour les paiements."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class PaymentCreate(BaseModel):
    enrollment_fee_id: int
    amount: Decimal
    method: str
    reference: str | None = None
    notes: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v

    @field_validator("method")
    @classmethod
    def valid_method(cls, v: str) -> str:
        allowed = {"cash", "mobile_money", "bank_transfer", "cheque"}
        if v not in allowed:
            raise ValueError(f"method must be one of {sorted(allowed)}")
        return v


class PaymentResponse(BaseModel):
    id: int
    enrollment_fee_id: int
    amount: Decimal
    method: str
    status: str
    reference: str | None
    received_by: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    # Enriched from joins
    student_name: str | None = None
    student_photo_url: str | None = None
    fee_name: str | None = None


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    page: int
    size: int


class PaymentSummaryResponse(BaseModel):
    total_expected: float
    total_paid: float
    total_pending: float
    total_cancelled: float
    payment_count: int
    completion_rate: float
