"""Service de gestion des comptes de connexion des acteurs.

Consultation / création / réinitialisation du `User` rattaché à un profil
élève, parent, enseignant ou personnel. Mot de passe temporaire `Bonjour@<année>`
avec changement forcé à la 1re connexion (`must_change_password`).
"""

import logging
import unicodedata
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.user import Parent, StaffProfile, Student, TeacherProfile, User, UserRoleEnum
from app.repositories.user_repository import get_user_by_id
from app.schemas.account import AccountActionResponse, AccountStatusResponse

logger = logging.getLogger(__name__)

# entity_type → (modèle profil, rôle du compte). Ordre = source de vérité.
_ENTITY_CONFIG: dict[str, tuple[type, UserRoleEnum, str]] = {
    "student": (Student, UserRoleEnum.STUDENT, "student"),
    "parent": (Parent, UserRoleEnum.PARENT, "parent"),
    "teacher": (TeacherProfile, UserRoleEnum.TEACHER, "teacher"),
    "staff": (StaffProfile, UserRoleEnum.STAFF, "staff"),
}
# Types dont le profil peut exister SANS compte (user_id nullable) → « créer ».
_CREATABLE = {"student", "parent"}


def _default_password() -> str:
    """Mot de passe temporaire `Bonjour@<année grégorienne courante>`."""
    return f"Bonjour@{date.today().year}"


def _slug(value: str) -> str:
    """Normalise un nom pour un email : minuscules, sans accents ni séparateurs."""
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(c for c in ascii_only.lower() if c.isalnum())


def _validate_entity_type(entity_type: str) -> tuple[type, UserRoleEnum, str]:
    config = _ENTITY_CONFIG.get(entity_type)
    if config is None:
        raise NotFoundError("Type d'acteur", 0)
    return config


async def _get_profile(db: AsyncSession, model: type, entity_id: int):
    profile = (await db.execute(select(model).where(model.id == entity_id))).scalar_one_or_none()
    if profile is None:
        raise NotFoundError(model.__name__, entity_id)
    return profile


def _full_name(profile) -> str:
    return f"{profile.first_name} {profile.last_name}".strip()


def _suggest_email(profile, entity_type: str) -> str:
    # Parent : réutiliser son email de contact s'il existe.
    existing = getattr(profile, "email", None)
    if existing:
        return existing
    return f"{_slug(profile.first_name)}.{_slug(profile.last_name)}@{entity_type}.klassci.ci"


async def get_account_status(
    db: AsyncSession, entity_type: str, entity_id: int
) -> AccountStatusResponse:
    model, _role_enum, _role_name = _validate_entity_type(entity_type)
    profile = await _get_profile(db, model, entity_id)

    user = None
    if profile.user_id is not None:
        user = await get_user_by_id(db, profile.user_id)

    if user is not None:
        return AccountStatusResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            full_name=_full_name(profile),
            has_account=True,
            can_create=False,
            user_id=user.id,
            email=user.email,
            is_active=user.is_active,
            last_login=user.last_login,
            must_change_password=user.must_change_password,
        )

    return AccountStatusResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        full_name=_full_name(profile),
        has_account=False,
        can_create=entity_type in _CREATABLE,
        suggested_email=_suggest_email(profile, entity_type),
    )


async def create_account(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    email: str,
    created_by: int,
) -> AccountActionResponse:
    model, role_enum, role_name = _validate_entity_type(entity_type)
    if entity_type not in _CREATABLE:
        raise BusinessValidationError("Ce type d'acteur possède déjà un compte à sa création.")
    profile = await _get_profile(db, model, entity_id)
    if profile.user_id is not None:
        raise ConflictError("Cet acteur a déjà un compte.")

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"L'email {email} est déjà utilisé.")

    # Import tardif pour éviter un cycle admin_service ↔ account_service.
    from app.services.admin_service import _ensure_default_user_role

    password = _default_password()
    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=role_enum,
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    await _ensure_default_user_role(db, user.id, role_name)
    profile.user_id = user.id

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.CREATE,
        user_id=created_by,
        entity_id=entity_id,
        new_values={"account_user_id": user.id, "email": email},
    )
    await db.commit()

    return AccountActionResponse(
        user_id=user.id,
        email=email,
        temporary_password=password,
        must_change_password=True,
    )


async def reset_password(
    db: AsyncSession,
    entity_type: str,
    entity_id: int,
    reset_by: int,
) -> AccountActionResponse:
    model, _role_enum, _role_name = _validate_entity_type(entity_type)
    profile = await _get_profile(db, model, entity_id)
    if profile.user_id is None:
        raise BusinessValidationError("Cet acteur n'a pas encore de compte.")

    user = await get_user_by_id(db, profile.user_id)
    if user is None:
        raise NotFoundError("User", profile.user_id)

    password = _default_password()
    user.hashed_password = hash_password(password)
    user.must_change_password = True

    await audit_log(
        db,
        entity_type=entity_type,
        action=AuditAction.UPDATE,
        user_id=reset_by,
        entity_id=entity_id,
        new_values={"password_reset_for_user_id": user.id},
    )
    await db.commit()

    return AccountActionResponse(
        user_id=user.id,
        email=user.email,
        temporary_password=password,
        must_change_password=True,
    )
