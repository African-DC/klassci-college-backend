"""Config MailPulse par tenant — lecture, écriture, construction du client.

La config vit dans le singleton ``school_settings`` (colonnes ``mailpulse_*``).
La clé API est un secret : jamais renvoyée, une valeur vide en update la conserve.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.config import settings as app_settings
from app.models.academic import SchoolSettings
from app.schemas.mailpulse import (
    MailPulseConfigResponse,
    MailPulseConfigUpdate,
    MailPulseRecipient,
)
from app.services import admin_service
from app.services.mailpulse.client import MailPulseClient

_UPDATABLE_FIELDS = (
    "enabled",
    "base_url",
    "sender_email",
    "sender_name",
    "default_language",
    "timeout",
    "real_workflows_enabled",
    "test_email_enabled",
    "test_whatsapp_enabled",
)


def _recipients_from_json(raw: Any) -> list[MailPulseRecipient]:
    if not isinstance(raw, list):
        return []
    out: list[MailPulseRecipient] = []
    for item in raw:
        if isinstance(item, dict) and item.get("value"):
            out.append(
                MailPulseRecipient(value=str(item["value"]), enabled=bool(item.get("enabled", True)))
            )
    return out


def config_to_response(school: SchoolSettings) -> MailPulseConfigResponse:
    """Projette le singleton en réponse — sans la clé API en clair."""
    return MailPulseConfigResponse(
        enabled=school.mailpulse_enabled,
        base_url=school.mailpulse_base_url or app_settings.MAILPULSE_BASE_URL,
        api_key_set=bool(school.mailpulse_api_key),
        sender_email=school.mailpulse_sender_email,
        sender_name=school.mailpulse_sender_name or app_settings.MAILPULSE_SENDER_NAME,
        default_language=school.mailpulse_default_language or app_settings.MAILPULSE_DEFAULT_LANGUAGE,
        timeout=school.mailpulse_timeout or app_settings.MAILPULSE_TIMEOUT,
        real_workflows_enabled=school.mailpulse_real_workflows_enabled,
        test_email_enabled=school.mailpulse_test_email_enabled,
        test_whatsapp_enabled=school.mailpulse_test_whatsapp_enabled,
        test_email_recipients=_recipients_from_json(school.mailpulse_test_email_recipients),
        test_phone_recipients=_recipients_from_json(school.mailpulse_test_phone_recipients),
        inbound_secret_set=bool(school.mailpulse_inbound_secret),
    )


async def get_config(db: AsyncSession) -> MailPulseConfigResponse:
    """Config MailPulse du tenant (singleton lazy-bootstrapé)."""
    school = await admin_service.get_school_settings(db)
    return config_to_response(school)


async def update_config(
    db: AsyncSession, data: MailPulseConfigUpdate, *, updated_by: int
) -> MailPulseConfigResponse:
    """Met à jour la config. Clé API vide/absente = conservée. Audit sans secret."""
    school = await admin_service.get_school_settings(db)

    async with db.begin_nested():
        for field in _UPDATABLE_FIELDS:
            setattr(school, f"mailpulse_{field}", getattr(data, field))

        # Clé API : ne remplacer que si une nouvelle valeur non vide est fournie.
        if data.api_key and data.api_key.strip():
            school.mailpulse_api_key = data.api_key.strip()

        # Secret webhook entrant : même règle (write-only, vide = conservé).
        if data.inbound_secret and data.inbound_secret.strip():
            school.mailpulse_inbound_secret = data.inbound_secret.strip()

        school.mailpulse_test_email_recipients = [
            r.model_dump() for r in data.test_email_recipients if r.value
        ]
        school.mailpulse_test_phone_recipients = [
            r.model_dump() for r in data.test_phone_recipients if r.value
        ]

        await db.flush()
        await audit_log(
            db,
            entity_type="school_settings",
            entity_id=school.id,
            action=AuditAction.UPDATE,
            user_id=updated_by,
            # Jamais la clé API dans l'audit — seulement les flags/état.
            new_values={
                "mailpulse_enabled": data.enabled,
                "mailpulse_real_workflows_enabled": data.real_workflows_enabled,
                "mailpulse_api_key_changed": bool(data.api_key and data.api_key.strip()),
                "test_email_recipients_count": len(school.mailpulse_test_email_recipients),
                "test_phone_recipients_count": len(school.mailpulse_test_phone_recipients),
            },
        )
    await db.commit()
    return config_to_response(school)


def build_client(school: SchoolSettings) -> MailPulseClient | None:
    """Construit un client MailPulse depuis la config tenant, ou None si absente.

    Retourne None si la clé API n'est pas configurée (rien à envoyer).
    """
    api_key = school.mailpulse_api_key
    if not api_key:
        return None
    return MailPulseClient(
        api_key=api_key,
        base_url=school.mailpulse_base_url or app_settings.MAILPULSE_BASE_URL,
        timeout=school.mailpulse_timeout or app_settings.MAILPULSE_TIMEOUT,
        contacts_endpoint=app_settings.MAILPULSE_CONTACTS_ENDPOINT,
        messages_endpoint=app_settings.MAILPULSE_MESSAGES_ENDPOINT,
    )
