"""Schémas Pydantic pour l'authentification."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserInToken(BaseModel):
    id: int
    email: str
    role: Literal["admin", "staff", "teacher", "student", "parent", "super_admin"]
    first_name: str
    last_name: str
    # Force l'écran de changement de mot de passe à la 1re connexion (compte créé
    # ou réinitialisé par un admin avec un mot de passe temporaire).
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


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
