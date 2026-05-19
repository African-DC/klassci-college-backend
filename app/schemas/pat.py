"""Pydantic schemas for Personal Access Token endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.pat_service import DEFAULT_EXPIRY_DAYS


class PATCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    scopes: list[str] = Field(..., min_length=1, max_length=20)
    expires_in_days: int = Field(DEFAULT_EXPIRY_DAYS, ge=1, le=365)

    @field_validator("scopes")
    @classmethod
    def reject_blank_scopes(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v if s.strip()]
        if not cleaned:
            raise ValueError("At least one non-empty scope is required")
        return cleaned


class PATListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    token_prefix: str
    scopes: list[str]
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class PATCreateResponse(PATListItem):
    plaintext: str = Field(
        ...,
        description="The unhashed token. Returned exactly once — store it in keyring immediately.",
    )


class PATListResponse(BaseModel):
    items: list[PATListItem]
    total: int
