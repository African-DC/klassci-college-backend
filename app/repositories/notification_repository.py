"""Repository notifications — accès DB pour Notification."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def get_notification_by_id(db: AsyncSession, notification_id: int) -> Notification | None:
    """Retourne une notification par ID."""
    stmt = select(Notification).where(Notification.id == notification_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: int,
    type: str | None = None,
    read: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Notification], int]:
    """Retourne une page de notifications pour un utilisateur avec le total."""
    base = select(Notification).where(Notification.user_id == user_id)
    if type is not None:
        base = base.where(Notification.type == type)
    if read is not None:
        base = base.where(Notification.read == read)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Notification.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def count_unread(db: AsyncSession, user_id: int) -> int:
    """Compte les notifications non-lues pour un utilisateur."""
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
    )
    return (await db.execute(stmt)).scalar() or 0


async def mark_as_read(db: AsyncSession, notification: Notification) -> Notification:
    """Marque une notification comme lue."""
    notification.read = True
    notification.read_at = func.now()
    await db.flush()
    return notification


async def mark_all_read(db: AsyncSession, user_id: int) -> int:
    """Marque toutes les notifications non-lues d'un utilisateur comme lues.

    Retourne le nombre de lignes mises à jour.
    """
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
        .values(read=True, read_at=func.now())
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount


async def mark_seen(db: AsyncSession, user_id: int, notification_ids: list[int]) -> int:
    """Marque comme lues les notifications désignées, et elles seules.

    Le filtre sur `user_id` n'est pas une précaution de style : sans lui,
    n'importe qui pourrait faire disparaître les alertes d'un collègue en
    envoyant ses identifiants.

    Retourne le nombre de lignes réellement modifiées — celles déjà lues n'y
    figurent pas, ce qui permet à l'appelant de savoir si le compteur bouge.
    """
    if not notification_ids:
        return 0
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.id.in_(notification_ids),
            Notification.read == False,  # noqa: E712
        )
        .values(read=True, read_at=func.now())
    )
    result = await db.execute(stmt)
    await db.flush()
    return result.rowcount
