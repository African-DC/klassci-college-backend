"""Router notifications — endpoints utilisateur pour les notifications in-app."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.schemas.notification import (
    MarkAllReadResponse,
    MarkSeenRequest,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    type: str | None = Query(None),
    read: bool | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> NotificationListResponse:
    """Liste paginée des notifications de l'utilisateur courant."""
    return await notification_service.list_notifications(
        db, user_id=current_user.user_id, type=type, read=read, page=page, size=size
    )


@router.get("/count", response_model=UnreadCountResponse)
async def get_unread_count(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> UnreadCountResponse:
    """Nombre de notifications non-lues (pour le badge navbar)."""
    return await notification_service.get_unread_count(db, user_id=current_user.user_id)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> NotificationResponse:
    """Marque une notification comme lue."""
    return await notification_service.mark_as_read(
        db, notification_id=notification_id, user_id=current_user.user_id
    )


@router.post("/read-all", response_model=MarkAllReadResponse)
async def mark_all_read(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> MarkAllReadResponse:
    """Marque toutes les notifications non-lues comme lues."""
    return await notification_service.mark_all_read(db, user_id=current_user.user_id)


@router.post("/mark-seen", response_model=MarkAllReadResponse)
async def mark_seen(
    payload: MarkSeenRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> MarkAllReadResponse:
    """Marque comme lues les notifications que le panneau vient d'afficher.

    Distinct de `/read-all` : ouvrir la cloche ne veut pas dire avoir tout lu.
    Effacer le stock entier ferait disparaitre des taches que personne n'a
    vues, ce qu'un compteur est justement cense empecher.
    """
    return await notification_service.mark_seen(
        db, user_id=current_user.user_id, notification_ids=payload.notification_ids
    )
