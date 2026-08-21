"""Repository permissions — vérifie qu'un utilisateur possède un slug de permission."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission, Role, RolePermission, UserRole


async def check_user_permission(db: AsyncSession, user_id: int, slug: str) -> bool:
    """Retourne True si l'utilisateur possède la permission identifiée par slug.

    Chemin : UserRole → Role → RolePermission → Permission (slug).
    """
    stmt = select(
        exists(
            select(UserRole.id)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user_id, Permission.slug == slug)
        )
    )
    result = await db.execute(stmt)
    return bool(result.scalar())


async def list_user_permissions(db: AsyncSession, user_id: int) -> list[str]:
    """Retourne la liste des slugs de permissions effectives de l'utilisateur.

    Utilisé par l'endpoint /auth/me/permissions pour le gating UI côté FE.
    """
    stmt = (
        select(Permission.slug)
        .distinct()
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
        .order_by(Permission.slug)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def list_roles_with_permission(db: AsyncSession, slug: str) -> list[str]:
    """Noms lisibles des rôles qui détiennent cette permission.

    Sert à rendre un refus actionnable : dire « vous ne pouvez pas encaisser en
    espèces » sans dire qui le peut oblige la personne au guichet à aller
    demander, la famille devant elle.
    """
    stmt = (
        select(Role.description, Role.name)
        .distinct()
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.slug == slug)
        .order_by(Role.name)
    )
    result = await db.execute(stmt)
    return [description or name for description, name in result.all()]


async def list_roles_holding(db: AsyncSession, slug: str) -> list[Role]:
    """Les rôles qui détiennent ce slug, objets complets.

    Sert à ne présenter dans l'écran de configuration que les profils qui
    encaissent réellement : proposer de régler les moyens de paiement d'un
    enseignant n'apprendrait rien à personne.
    """
    stmt = (
        select(Role)
        .distinct()
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.slug == slug)
        .order_by(Role.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def permission_ids_by_slug(db: AsyncSession, slugs: list[str]) -> dict[str, int]:
    """Identifiants des permissions demandées, par slug.

    Un slug absent n'apparaît pas dans le retour : l'appelant décide quoi en
    faire, plutôt que de recevoir un `None` qui finirait écrit en base.
    """
    if not slugs:
        return {}
    stmt = select(Permission.slug, Permission.id).where(Permission.slug.in_(slugs))
    return dict((await db.execute(stmt)).all())  # type: ignore[arg-type]


async def role_permission_slugs(db: AsyncSession, role_id: int) -> set[str]:
    """Slugs détenus par un rôle."""
    stmt = (
        select(Permission.slug)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return {row[0] for row in (await db.execute(stmt)).all()}
