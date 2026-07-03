"""Schémas du profil self-service (l'utilisateur consulte/édite son propre profil)."""

from datetime import datetime

from pydantic import BaseModel


class MyProfileResponse(BaseModel):
    user_id: int
    email: str
    role: str
    first_name: str
    last_name: str
    phone: str | None = None
    photo_url: str | None = None
    position: str | None = None
    speciality: str | None = None
    # Capacités self-service selon le rôle (l'élève ne gère pas sa photo lui-même).
    can_edit_photo: bool = False
    can_edit_phone: bool = False
    last_login: datetime | None = None
    created_at: datetime | None = None


class MyProfileUpdate(BaseModel):
    phone: str | None = None


class PhotoUrlResponse(BaseModel):
    photo_url: str | None = None
