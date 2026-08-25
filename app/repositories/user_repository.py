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


async def get_teacher_profile_id(db: AsyncSession, user_id: int) -> int | None:
    """Retourne le teacher_profiles.id pour un user donné, ou None si non-enseignant."""
    stmt = select(TeacherProfile.id).where(TeacherProfile.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none()


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


#: Ce qu'on écrit quand un compte n'est plus identifiable du tout.
UNNAMED_PERSON = "—"


def format_person_name(first_name: str | None, last_name: str | None, email: str | None) -> str:
    """Nom lisible d'une personne, avec les mêmes replis partout.

    Deux documents produits par la même école doivent nommer la même personne
    de la même façon. Le bordereau de caisse et le journal des versements
    passaient par des replis différents — l'un montrait l'adresse e-mail
    entière, l'autre sa partie gauche — et deux pièces comptables du même jour
    désignaient le même caissier sous deux noms.

    Ordre : le nom du profil, puis la partie gauche de l'adresse e-mail, qui
    identifie encore, puis un tiret cadratin explicite.
    """
    complet = " ".join(part for part in (first_name, last_name) if part).strip()
    if complet:
        return complet
    local = (email or "").split("@")[0].strip()
    return local or UNNAMED_PERSON
