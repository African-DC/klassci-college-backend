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
from app.repositories import permission_repository
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
    *,
    action_url: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
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

    # Respecte les préférences de canaux de l'utilisateur (l'in-app reste toujours actif).
    from app.services import notification_pref_service

    enabled = await notification_pref_service.get_enabled_channels(db, user_id)
    requested_channels = {
        c for c in requested_channels if c == NotificationChannel.IN_APP.value or c in enabled
    }

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
        action_url=action_url,
        entity_type=entity_type,
        entity_id=entity_id,
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


async def dispatch_to_permission(
    db: AsyncSession,
    permission_slug: str,
    notification_type: str | NotificationType,
    context: dict[str, str],
    channels: list[str | NotificationChannel] | None = None,
    *,
    action_url: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    exclude_user_id: int | None = None,
) -> list[Notification]:
    """Prévient quiconque a le droit de faire ce que la notification annonce.

    On ne s'adresse pas à un rôle nommé. Une école confie l'encaissement à sa
    secrétaire, une autre à un caissier, une troisième au directeur lui-même :
    coder « caissier » ici obligerait à modifier le produit à chaque école.
    La permission, elle, dit exactement ce qu'on cherche — la personne qui
    peut encaisser — quel que soit le nom qu'on lui donne.

    `exclude_user_id` évite d'écrire à celui qui vient d'agir. Recevoir la
    notification de sa propre action n'apprend rien et use le compteur : c'est
    justement ce qui fait qu'on cesse de regarder la cloche.

    Retourne les notifications créées, éventuellement aucune — et ce cas
    mérite un log : une tâche sans destinataire est une tâche que personne ne
    verra, ce qui est un défaut de configuration, pas un silence normal.
    """
    user_ids = await permission_repository.list_user_ids_with_permission(db, permission_slug)
    destinataires = [uid for uid in user_ids if uid != exclude_user_id]

    if not destinataires:
        logger.warning(
            "Notification '%s' sans destinataire : personne ne detient '%s'",
            notification_type,
            permission_slug,
        )
        return []

    envoyees: list[Notification] = []
    for uid in destinataires:
        try:
            envoyees.append(
                await dispatch_notification(
                    db,
                    uid,
                    notification_type,
                    context,
                    channels,
                    action_url=action_url,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )
            )
        except Exception:
            # Un destinataire injoignable ne doit pas priver les autres : la
            # notification est un effet de bord de l'acte metier, jamais sa
            # condition. L'inscription reste creee meme si la cloche echoue.
            logger.exception("Notification '%s' echouee pour l'utilisateur %d", notification_type, uid)

    return envoyees
