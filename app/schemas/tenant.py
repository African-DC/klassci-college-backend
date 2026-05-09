"""Schémas Pydantic pour les opérations super-admin sur les tenants."""

from typing import Any

from pydantic import BaseModel, EmailStr, field_validator

from app.core.slug import validate_tenant_slug


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
        return validate_tenant_slug(v)

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
    return TenantDetailResponse.model_validate(payload)
