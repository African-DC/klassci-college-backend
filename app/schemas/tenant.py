"""Schémas Pydantic pour les opérations super-admin sur les tenants."""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


class TenantProvisionRequest(BaseModel):
    tenant_slug: str
    school_name: str
    admin_email: EmailStr
    admin_password: str
    school_address: str | None = None
    school_phone: str | None = None
    school_email: EmailStr | None = None
    ministry_code: str | None = None

    @field_validator("tenant_slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$", v):
            raise ValueError("Must be 2-63 chars, lowercase alphanumeric + hyphens")
        return v

    @field_validator("admin_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class TenantProvisionResponse(BaseModel):
    tenant_slug: str
    database: str
    admin_email: str
    status: str
    url: str


class TenantListItem(BaseModel):
    slug: str
    url: str
    db_size_bytes: int
    created_at: datetime | None = None


class TenantListResponse(BaseModel):
    items: list[TenantListItem]
    total: int


class TenantSchoolSettings(BaseModel):
    school_name: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    ministry_code: str | None = None


class TenantCounts(BaseModel):
    users: int
    students: int
    teachers: int
    staff: int
    enrollments: int
    payments: int


class TenantDetailResponse(BaseModel):
    slug: str
    url: str
    school_settings: TenantSchoolSettings | None = None
    counts: TenantCounts
    alembic_head: str | None = None
    db_size_bytes: int


class SlugCheckRequest(BaseModel):
    slug: str

    @field_validator("slug")
    @classmethod
    def normalise(cls, v: str) -> str:
        return v.strip().lower()


class SlugCheckResponse(BaseModel):
    slug: str
    available: bool
    valid_format: bool
    reason: str | None = None


def to_detail_response(payload: dict[str, Any]) -> TenantDetailResponse:
    return TenantDetailResponse(
        slug=payload["slug"],
        url=payload["url"],
        school_settings=(
            TenantSchoolSettings(**payload["school_settings"])
            if payload.get("school_settings")
            else None
        ),
        counts=TenantCounts(**payload["counts"]),
        alembic_head=payload.get("alembic_head"),
        db_size_bytes=payload["db_size_bytes"],
    )
