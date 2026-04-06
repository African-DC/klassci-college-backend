"""Service notifications — logique métier lecture/marquage."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.repositories import notification_repository as repo
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

logger = logging.getLogger(__name__)


def _to_response(notification: object) -> NotificationResponse:
    """Convertit un Notification ORM en NotificationResponse."""
    return NotificationResponse.model_validate(notification)


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: int,
    type: str | None = None,
    read: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> NotificationListResponse:
    """Retourne une page de notifications pour l'utilisateur courant."""
    notifications, total = await repo.list_notifications(
        db, user_id=user_id, type=type, read=read, page=page, size=size
    )
    return NotificationListResponse(
        items=[_to_response(n) for n in notifications],
        total=total,
        page=page,
        size=size,
    )


async def get_unread_count(db: AsyncSession, *, user_id: int) -> UnreadCountResponse:
    """Retourne le nombre de notifications non-lues."""
    count = await repo.count_unread(db, user_id)
    return UnreadCountResponse(count=count)


async def mark_as_read(
    db: AsyncSession, *, notification_id: int, user_id: int
) -> NotificationResponse:
    """Marque une notification comme lue après vérification de propriété."""
    notification = await repo.get_notification_by_id(db, notification_id)
    if notification is None:
        raise NotFoundError("Notification", notification_id)
    if notification.user_id != user_id:
        raise PermissionDeniedError("Cannot mark another user's notification as read")

    updated = await repo.mark_as_read(db, notification)
    await db.commit()
    return _to_response(updated)


async def mark_all_read(db: AsyncSession, *, user_id: int) -> MarkAllReadResponse:
    """Marque toutes les notifications non-lues comme lues."""
    count = await repo.mark_all_read(db, user_id)
    await db.commit()
    return MarkAllReadResponse(updated=count)
