"""Service de dispatch multi-canal des notifications.

Crée toujours une notification in-app, puis envoie par email et/ou SMS
selon les canaux demandés.
"""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notification import (
    Notification,
    NotificationChannel,
    NotificationTemplate,
    NotificationType,
)
from app.models.user import User
from app.services.email_service import send_email
from app.services.sms_service import send_sms

logger = logging.getLogger(__name__)


def _render_template(template_body: str, context: dict[str, str]) -> str:
    """Remplace les {{var}} dans le template par les valeurs du contexte."""

    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        return str(context.get(key, match.group(0)))

    return re.sub(r"\{\{(\w+)\}\}", _replacer, template_body)


async def _get_template(
    db: AsyncSession,
    notification_type: str,
    channel: str,
    language: str = "fr",
) -> NotificationTemplate | None:
    """Récupère un template par type, canal et langue."""
    stmt = select(NotificationTemplate).where(
        NotificationTemplate.type == notification_type,
        NotificationTemplate.channel == channel,
        NotificationTemplate.language == language,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_with_profiles(db: AsyncSession, user_id: int) -> User | None:
    """Charge un utilisateur avec ses profils pour accéder au téléphone."""
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.parent_profile),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _get_user_phone(user: User) -> str | None:
    """Extrait le numéro de téléphone depuis le profil de l'utilisateur."""
    if user.staff_profile and user.staff_profile.phone:
        return user.staff_profile.phone
    if user.teacher_profile and user.teacher_profile.phone:
        return user.teacher_profile.phone
    if user.parent_profile and user.parent_profile.phone:
        return user.parent_profile.phone
    return None


async def dispatch_notification(
    db: AsyncSession,
    user_id: int,
    notification_type: str | NotificationType,
    context: dict[str, str],
    channels: list[str | NotificationChannel] | None = None,
) -> Notification:
    """Dispatche une notification sur les canaux demandés.

    - Crée toujours une notification in-app.
    - Si email est demandé : récupère le template email, rend le HTML, envoie.
    - Si SMS est demandé : récupère le template SMS, rend le body, envoie.

    Args:
        db: session async SQLAlchemy
        user_id: destinataire
        notification_type: type de notification (enum value ou string)
        context: variables pour le rendu des templates (ex: {"student_name": "…"})
        channels: canaux supplémentaires (en plus d'in_app). None = in_app uniquement.

    Returns:
        La notification in-app créée.
    """
    n_type = (
        notification_type.value
        if isinstance(notification_type, NotificationType)
        else notification_type
    )
    requested_channels: set[str] = {NotificationChannel.IN_APP.value}
    if channels:
        for ch in channels:
            requested_channels.add(ch.value if isinstance(ch, NotificationChannel) else ch)

    # ── Charger l'utilisateur avec profils ──
    user = await _get_user_with_profiles(db, user_id)
    if user is None:
        logger.error("Cannot dispatch notification — user %d not found", user_id)
        raise ValueError(f"User {user_id} not found")

    # ── Template in-app (obligatoire) ──
    in_app_template = await _get_template(db, n_type, NotificationChannel.IN_APP.value)
    if in_app_template:
        title = _render_template(in_app_template.subject or n_type, context)
        body = _render_template(in_app_template.body, context)
    else:
        # Fallback : utiliser le contexte directement
        title = context.get("title", n_type)
        body = context.get("body", "")

    # ── Créer la notification in-app ──
    notification = Notification(
        user_id=user_id,
        type=n_type,
        channel=NotificationChannel.IN_APP.value,
        title=title,
        body=body,
        read=False,
        sent_at=datetime.now(UTC),
    )
    db.add(notification)
    await db.flush()
    logger.info("In-app notification #%d created for user %d", notification.id, user_id)

    # ── Email ──
    if NotificationChannel.EMAIL.value in requested_channels:
        email_template = await _get_template(db, n_type, NotificationChannel.EMAIL.value)
        if email_template:
            subject = _render_template(email_template.subject or title, context)
            html_body = _render_template(email_template.body, context)
        else:
            subject = title
            html_body = f"<p>{body}</p>"

        sent = send_email(user.email, subject, html_body)
        if sent:
            logger.info("Email notification sent to %s for type %s", user.email, n_type)

    # ── SMS ──
    if NotificationChannel.SMS.value in requested_channels:
        phone = _get_user_phone(user)
        if phone:
            sms_template = await _get_template(db, n_type, NotificationChannel.SMS.value)
            if sms_template:
                sms_body = _render_template(sms_template.body, context)
            else:
                sms_body = body

            sent = send_sms(phone, sms_body)
            if sent:
                logger.info("SMS notification sent to %s for type %s", phone, n_type)
        else:
            logger.warning("No phone number for user %d — SMS skipped", user_id)

    return notification
