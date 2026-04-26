"""Service d'envoi de SMS via Twilio."""

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_configured() -> bool:
    """Vérifie que les paramètres Twilio sont renseignés."""
    return bool(
        settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_PHONE_NUMBER
    )


def send_sms(to_phone: str, body: str) -> bool:
    """Envoie un SMS via Twilio.

    Retourne True si l'envoi réussit, False sinon.
    Si Twilio n'est pas configuré, log un warning et retourne False.
    """
    if not _is_configured():
        logger.warning("Twilio not configured — SMS to %s skipped", to_phone)
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to_phone,
        )
        logger.info("SMS sent to %s — SID: %s", to_phone, message.sid)
        return True
    except Exception:
        logger.exception("Failed to send SMS to %s", to_phone)
        return False
