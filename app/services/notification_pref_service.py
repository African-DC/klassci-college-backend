"""Préférences de canaux de notification (email / SMS) par utilisateur.

L'in-app (cloche) est toujours actif. Ces préférences filtrent les canaux
supplémentaires au moment du dispatch.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import NotificationChannel, NotificationPreference


async def _ensure(db: AsyncSession, user_id: int) -> NotificationPreference:
    """Retourne la ligne de préférences, la crée avec les défauts si absente.

    Ne commit pas : sûr à appeler depuis le dispatch (dans la transaction de
    l'appelant). Les endpoints self-service commitent eux-mêmes.
    """
    stmt = select(NotificationPreference).where(NotificationPreference.user_id == user_id)
    prefs = (await db.execute(stmt)).scalar_one_or_none()
    if prefs is None:
        prefs = NotificationPreference(user_id=user_id, email=True, sms=False)
        db.add(prefs)
        await db.flush()
    return prefs


async def get_prefs(db: AsyncSession, user_id: int) -> dict:
    prefs = await _ensure(db, user_id)
    email, sms = prefs.email, prefs.sms
    await db.commit()
    return {"email": email, "sms": sms}


async def update_prefs(
    db: AsyncSession, user_id: int, *, email: bool | None, sms: bool | None
) -> dict:
    prefs = await _ensure(db, user_id)
    if email is not None:
        prefs.email = email
    if sms is not None:
        prefs.sms = sms
    result = {"email": prefs.email, "sms": prefs.sms}
    await db.commit()
    return result


async def get_enabled_channels(db: AsyncSession, user_id: int) -> set[str]:
    """Canaux autorisés (in-app toujours inclus). Ne commit pas."""
    prefs = await _ensure(db, user_id)
    channels = {NotificationChannel.IN_APP.value}
    if prefs.email:
        channels.add(NotificationChannel.EMAIL.value)
    if prefs.sms:
        channels.add(NotificationChannel.SMS.value)
    return channels
