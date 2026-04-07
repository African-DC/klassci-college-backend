"""Schemas Pydantic pour le CRUD des frais scolaires (FeeCategory, FeeVariant)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


# ---------------------------------------------------------------------------
# FeeCategory
# ---------------------------------------------------------------------------


class FeeCategoryCreate(BaseModel):
    name: str
    description: str | None = None


class FeeCategoryUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class FeeCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class FeeCategoryListResponse(BaseModel):
    items: list[FeeCategoryResponse]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# FeeVariant
# ---------------------------------------------------------------------------


class FeeVariantCreate(BaseModel):
    fee_category_id: int
    class_id: int | None = None
    level_id: int | None = None
    series_id: int | None = None
    academic_year_id: int
    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class FeeVariantUpdate(BaseModel):
    amount: Decimal | None = None
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive")
        return v


class FeeVariantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_category_id: int
    class_id: int | None
    level_id: int | None
    series_id: int | None
    academic_year_id: int
    amount: Decimal
    description: str | None
    created_at: datetime
    updated_at: datetime


class FeeVariantListResponse(BaseModel):
    items: list[FeeVariantResponse]
    total: int
    page: int
    size: int
