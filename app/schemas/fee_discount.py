"""Contrats des remises accordées à une inscription."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

class DiscountInput(BaseModel):
    kind: Literal["fixed", "percent"]
    value: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    reason: str = Field(min_length=5, max_length=255)

    @model_validator(mode="after")
    def validate_percentage(self):
        if self.kind == "percent" and self.value > 100:
            raise ValueError("Le pourcentage ne peut pas dépasser 100.")
        self.reason = self.reason.strip()
        if len(self.reason) < 5:
            raise ValueError("Le motif doit préciser la décision.")
        return self

class DiscountLine(BaseModel):
    fee_id: int
    category_name: str
    original_amount: Decimal
    payable_amount: Decimal
    discount_kind: str | None
    discount_value: Decimal | None
    discount_amount: Decimal
    discount_reason: str | None
