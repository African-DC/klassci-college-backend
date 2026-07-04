"""Schémas de gestion des comptes de connexion des acteurs.

Un « compte » = un `User` (email + mot de passe + rôle) rattaché au profil d'un
élève, parent, enseignant ou membre du personnel. L'admin peut consulter le
compte, le créer s'il n'existe pas (élève/parent), et réinitialiser le mot de
passe. Le mot de passe temporaire est `Bonjour@<année>` avec changement forcé
à la 1re connexion.
"""

from datetime import datetime

from pydantic import BaseModel, EmailStr


class AccountStatusResponse(BaseModel):
    entity_type: str
    entity_id: int
    full_name: str
    has_account: bool
    can_create: bool
    user_id: int | None = None
    email: str | None = None
    is_active: bool = False
    last_login: datetime | None = None
    must_change_password: bool = False
    # Email suggéré (pré-rempli, éditable) quand il n'y a pas encore de compte.
    suggested_email: str | None = None


class AccountCreateRequest(BaseModel):
    email: EmailStr


class AccountActionResponse(BaseModel):
    user_id: int
    email: str
    # Mot de passe temporaire communiqué à l'admin (valeur connue `Bonjour@AAAA`,
    # pas un secret) ; l'utilisateur devra le changer à la 1re connexion.
    temporary_password: str
    must_change_password: bool = True
