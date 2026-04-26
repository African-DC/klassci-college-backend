"""Schémas Pydantic pour le provisioning de tenants."""

import re

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
