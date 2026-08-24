"""Schémas Pydantic pour les notifications."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: str
    channel: str
    title: str
    body: str
    read: bool
    sent_at: datetime | None
    read_at: datetime | None
    entity_type: str | None
    entity_id: int | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    page: int
    size: int


class UnreadCountResponse(BaseModel):
    count: int


class MarkSeenRequest(BaseModel):
    """Les notifications que le panneau vient d'afficher."""

    notification_ids: list[int] = Field(
        ...,
        max_length=200,
        description="Identifiants des notifications affichees, au plus une page.",
    )


class MarkAllReadResponse(BaseModel):
    updated: int
