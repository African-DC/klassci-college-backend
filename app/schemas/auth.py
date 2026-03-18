"""Schémas Pydantic pour l'authentification."""

from typing import Literal

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserInToken(BaseModel):
    id: int
    email: str
    role: Literal["admin", "staff", "teacher", "student", "parent"]
    first_name: str
    last_name: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserInToken


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserMeResponse(BaseModel):
    id: int
    email: str
    role: str
    first_name: str
    last_name: str
    tenant_id: str
    is_active: bool
