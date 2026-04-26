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
