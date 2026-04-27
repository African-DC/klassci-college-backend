"""Repository permissions — vérifie qu'un utilisateur possède un slug de permission."""

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permission import Permission, RolePermission, UserRole


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
