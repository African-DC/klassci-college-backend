"""Modèles de notifications : Notification, NotificationTemplate."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, ValueEnum

if TYPE_CHECKING:
    from app.models.user import User


class NotificationType(str, enum.Enum):
    PAYMENT_DUE = "payment_due"
    PAYMENT_RECEIVED = "payment_received"
    GRADE_AVAILABLE = "grade_available"
    BULLETIN_PUBLISHED = "bulletin_published"
    ABSENCE_RECORDED = "absence_recorded"
    ENROLLMENT_STATUS = "enrollment_status"
    SYSTEM = "system"


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"


class Notification(Base, TimestampMixin):
    """Notification envoyée à un utilisateur."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        ValueEnum(NotificationType, name="notification_type"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        ValueEnum(NotificationChannel, name="notification_channel"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Lien optionnel vers l'entité concernée
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    user: Mapped[User] = relationship(back_populates="notifications")


class NotificationPreference(Base, TimestampMixin):
    """Préférences de canaux d'un utilisateur. L'in-app (cloche) est toujours actif."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sms: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NotificationTemplate(Base, TimestampMixin):
    """Gabarit de notification (sujet + corps avec variables {{var}})."""

    __tablename__ = "notification_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        ValueEnum(NotificationType, name="notification_type"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(
        ValueEnum(NotificationChannel, name="notification_channel"), nullable=False
    )
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="fr")
