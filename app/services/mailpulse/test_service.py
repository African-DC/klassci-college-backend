"""Moteur de test MailPulse — envoie un exemple vers les destinataires DE TEST.

Aucun vrai parent ni élève n'est impliqué. Les destinataires proviennent
exclusivement des listes de test configurées par tenant, filtrées par leur
interrupteur actif et par les interrupteurs de canal de test.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import SchoolSettings
from app.schemas.mailpulse import (
    MailPulseEvent,
    MailPulseTestChannel,
    MailPulseTestResponse,
    MailPulseTestResult,
)
from app.services import admin_service
from app.services.mailpulse.client import MailPulseClient
from app.services.mailpulse.settings_service import build_client

logger = logging.getLogger("mailpulse")

# Contenu d'exemple par évènement (données fictives — jamais un vrai élève).
_SAMPLE = {
    "payment_received": (
        "Reçu de paiement",
        "Test KLASSCI : un versement de 50 000 FCFA a été enregistré pour "
        "Awa Kouadio (6e A). Merci de votre confiance.",
    ),
    "absence_reported": (
        "Absence signalée",
        "Test KLASSCI : une absence d'Awa Kouadio (6e A) a été enregistrée. "
        "Contactez l'établissement pour toute question.",
    ),
    "grade_published": (
        "Nouvelle note disponible",
        "Test KLASSCI : une nouvelle note est disponible pour Awa Kouadio (6e A) en Mathématiques.",
    ),
    "fee_reminder": (
        "Rappel de frais",
        "Test KLASSCI : il reste 30 000 FCFA à régler pour la scolarité d'Awa Kouadio (6e A).",
    ),
}


def _enabled_values(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        str(item["value"]).strip()
        for item in raw
        if isinstance(item, dict) and item.get("value") and item.get("enabled", True)
    ]


def _plan(school: SchoolSettings, channel: MailPulseTestChannel) -> tuple[list[str], list[str]]:
    """Retourne (emails, phones) de test activés pour les canaux demandés."""
    emails: list[str] = []
    phones: list[str] = []
    if channel in ("email", "both") and school.mailpulse_test_email_enabled:
        emails = _enabled_values(school.mailpulse_test_email_recipients)
    if channel in ("whatsapp", "both") and school.mailpulse_test_whatsapp_enabled:
        phones = _enabled_values(school.mailpulse_test_phone_recipients)
    return emails, phones


async def send_test(
    db: AsyncSession,
    *,
    event: MailPulseEvent,
    channel: MailPulseTestChannel,
    dry_run: bool,
) -> MailPulseTestResponse:
    school = await admin_service.get_school_settings(db)
    subject, body = _SAMPLE[event]
    emails, phones = _plan(school, channel)

    if not emails and not phones:
        return MailPulseTestResponse(
            dry_run=dry_run,
            event=event,
            sent=0,
            results=[],
            message=(
                "Aucun destinataire de test actif pour ce canal. "
                "Ajoutez une adresse ou un numéro de test et activez son interrupteur."
            ),
        )

    if dry_run:
        results = [
            MailPulseTestResult(channel="email", recipient=e, ok=True, status="dry_run")
            for e in emails
        ] + [
            MailPulseTestResult(channel="whatsapp", recipient=p, ok=True, status="dry_run")
            for p in phones
        ]
        return MailPulseTestResponse(
            dry_run=True,
            event=event,
            sent=len(results),
            results=results,
            message=f"Simulation : {len(results)} envoi(s) préparé(s), aucun message réel émis.",
        )

    client = build_client(school)
    if client is None:
        return MailPulseTestResponse(
            dry_run=False,
            event=event,
            sent=0,
            results=[],
            message="Clé API MailPulse non configurée. Renseignez-la puis réessayez.",
        )

    results = await _send_all(client, school, subject, body, emails, phones, event)
    ok_count = sum(1 for r in results if r.ok)
    return MailPulseTestResponse(
        dry_run=False,
        event=event,
        sent=ok_count,
        results=results,
        message=f"{ok_count}/{len(results)} envoi(s) de test acceptés par MailPulse.",
    )


async def _send_all(
    client: MailPulseClient,
    school: SchoolSettings,
    subject: str,
    body: str,
    emails: list[str],
    phones: list[str],
    event: str,
) -> list[MailPulseTestResult]:
    results: list[MailPulseTestResult] = []
    for email in emails:
        await client.upsert_contact(email=email, language="fr")
        r = await client.send_message(
            channel="email",
            recipient=email,
            subject=subject,
            body=body,
            sender_email=school.mailpulse_sender_email,
            sender_name=school.mailpulse_sender_name,
            external_event_id=f"test-{event}",
        )
        results.append(
            MailPulseTestResult(
                channel="email",
                recipient=email,
                ok=r.ok,
                status=r.status,
                error_code=r.error_code,
                error_message=r.error_message,
            )
        )
    for phone in phones:
        await client.upsert_contact(phone=phone, language="fr")
        r = await client.send_message(
            channel="whatsapp",
            recipient=phone,
            subject=subject,
            body=body,
            external_event_id=f"test-{event}",
        )
        results.append(
            MailPulseTestResult(
                channel="whatsapp",
                recipient=phone,
                ok=r.ok,
                status=r.status,
                error_code=r.error_code,
                error_message=r.error_message,
            )
        )
    return results
