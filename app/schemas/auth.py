"""Schémas Pydantic pour l'authentification."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserInToken(BaseModel):
    id: int
    email: str
    role: Literal["admin", "staff", "teacher", "student", "parent"]
    first_name: str
    last_name: str


# Réponse body /login — refresh_token envoyé en cookie httpOnly, pas dans le body
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserInToken


# Réponse body /refresh
class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserMeResponse(BaseModel):
    id: int
    email: str
    role: str
    first_name: str
    last_name: str
    tenant_id: str
    is_active: bool
