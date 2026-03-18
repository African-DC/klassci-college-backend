"""Repository utilisateurs — accès DB pour User et profils associés."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import Parent, StaffProfile, Student, TeacherProfile, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Retourne l'utilisateur par email avec ses profils chargés."""
    stmt = (
        select(User)
        .where(User.email == email)
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
            selectinload(User.parent_profile),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    """Retourne l'utilisateur par ID avec ses profils chargés."""
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
            selectinload(User.parent_profile),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_last_login(db: AsyncSession, user_id: int) -> None:
    """Met à jour last_login de l'utilisateur à maintenant."""
    stmt = update(User).where(User.id == user_id).values(last_login=datetime.now(UTC))
    await db.execute(stmt)
    await db.commit()


def get_user_full_name(user: User) -> tuple[str, str]:
    """Extrait (first_name, last_name) depuis le bon profil selon le rôle."""
    profile: StaffProfile | TeacherProfile | Student | Parent | None = None
    if user.role in ("admin", "staff"):
        profile = user.staff_profile
    elif user.role == "teacher":
        profile = user.teacher_profile
    elif user.role == "student":
        profile = user.student_profile
    elif user.role == "parent":
        profile = user.parent_profile
    if profile is None:
        return ("", "")
    return (profile.first_name, profile.last_name)
