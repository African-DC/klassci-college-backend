"""Contrats API des réductions individualisées : XOF et pourcentages."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeeDiscountUpsert(BaseModel):
    kind: Literal["fixed", "percent"]
    value: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def non_empty_reason(cls, value: str) -> str:
        reason = value.strip()
        if len(reason) < 5:
            raise ValueError("Le motif doit comporter au moins cinq caractères.")
        return reason


class FeeDiscountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enrollment_fee_id: int
    original_amount: Decimal
    discount_amount: Decimal
    amount_due: Decimal
    kind: str
    value: Decimal
    reason: str
    granted_by: int | None
    created_at: datetime
    updated_at: datetime
