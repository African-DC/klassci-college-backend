"""Service profil self-service — l'utilisateur consulte et édite son propre profil.

Le nom, le téléphone et la photo vivent sur le profil métier (staff/teacher/
student/parent) résolu depuis `users.role`. L'élève ne peut pas changer sa
photo lui-même (géré par l'administration) ; le parent n'a pas de photo.
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.user import Parent, StaffProfile, Student, TeacherProfile, User
from app.repositories.user_repository import get_user_by_id
from app.schemas.profile import MyProfileUpdate

# Rôles dont le profil porte une photo qu'ils peuvent gérer eux-mêmes.
# L'élève a une photo mais géré par l'admin ; le parent n'a pas de photo.
PHOTO_SELF_ROLES = {"admin", "staff", "teacher"}

_ProfileEntity = StaffProfile | TeacherProfile | Student | Parent


def _profile_of(user: User) -> _ProfileEntity | None:
    if user.role in ("admin", "staff"):
        return user.staff_profile
    if user.role == "teacher":
        return user.teacher_profile
    if user.role == "student":
        return user.student_profile
    if user.role == "parent":
        return user.parent_profile
    return None


def _to_dict(user: User) -> dict:
    p = _profile_of(user)
    has_photo = hasattr(p, "photo_url")
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "first_name": getattr(p, "first_name", "") or "",
        "last_name": getattr(p, "last_name", "") or "",
        "phone": getattr(p, "phone", None),
        "photo_url": getattr(p, "photo_url", None),
        "position": getattr(p, "position", None),
        "speciality": getattr(p, "speciality", None),
        "can_edit_photo": user.role in PHOTO_SELF_ROLES and p is not None and has_photo,
        "can_edit_phone": p is not None and hasattr(p, "phone"),
        "last_login": user.last_login,
        "created_at": user.created_at,
    }


async def get_my_profile(db: AsyncSession, user_id: int) -> dict:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    return _to_dict(user)


async def update_my_profile(db: AsyncSession, user_id: int, data: MyProfileUpdate) -> dict:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    profile = _profile_of(user)
    if profile is None:
        raise HTTPException(status_code=400, detail="Aucun profil associé à ce compte")
    if data.phone is not None and hasattr(profile, "phone"):
        profile.phone = data.phone.strip() or None
    await db.commit()
    return await get_my_profile(db, user_id)


async def set_my_photo(db: AsyncSession, user_id: int, photo_url: str | None) -> str | None:
    """Change (ou retire si None) la photo de l'utilisateur. Enseignant/personnel/admin seulement."""
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise NotFoundError("User", user_id)
    if user.role not in PHOTO_SELF_ROLES:
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier votre photo")
    profile = _profile_of(user)
    if profile is None or not hasattr(profile, "photo_url"):
        raise HTTPException(status_code=400, detail="Aucun profil photo associé à ce compte")
    profile.photo_url = photo_url
    await db.commit()
    return photo_url
