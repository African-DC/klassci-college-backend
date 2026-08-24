"""Webhook entrant MailPulse — un parent écrit « INFO » sur WhatsApp.

MailPulse est aujourd'hui sortant seulement : ce récepteur est prêt à traiter
les messages entrants dès que MailPulse (ou un relais Meta/Baileys) les
transférera vers `POST /public/mailpulse/inbound/{tenant}`.

Sécurité : le tenant configure un secret partagé (`mailpulse_inbound_secret`)
présenté dans l'en-tête `X-MailPulse-Token`, vérifié en temps constant.
"""

import hmac
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import SchoolSettings
from app.models.user import Parent
from app.schemas.mailpulse import MailPulseInboundResult
from app.schemas.parent_portal import ParentDashboardChild
from app.services import admin_service, parent_portal_service
from app.services.mailpulse.client import normalize_phone_e164
from app.services.mailpulse.settings_service import build_client

logger = logging.getLogger("mailpulse")

_UNKNOWN_NUMBER_REPLY = (
    "Bonjour, ce numéro n'est pas encore reconnu comme parent dans notre "
    "établissement. Merci de contacter le secrétariat pour l'associer à votre compte."
)


def verify_secret(school: SchoolSettings, provided: str | None) -> bool:
    """Compare le secret présenté au secret tenant, en temps constant."""
    secret = school.mailpulse_inbound_secret
    if not secret or not provided:
        return False
    return hmac.compare_digest(provided, secret)


async def _find_parent_by_phone(db: AsyncSession, raw_phone: str) -> Parent | None:
    """Retrouve un parent par son numéro (comparaison sur les derniers chiffres)."""
    e164 = normalize_phone_e164(raw_phone)
    digits = "".join(ch for ch in (e164 or raw_phone) if ch.isdigit())
    if len(digits) < 8:
        return None
    last8 = digits[-8:]
    stmt = select(Parent).where(Parent.phone.like(f"%{last8}")).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def _fmt_amount(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _compose_info_reply(
    parent: Parent, children: list[ParentDashboardChild], school: SchoolSettings
) -> str:
    school_name = school.school_name or "notre établissement"
    lines = [
        f"Bonjour {parent.first_name}, voici les informations de vos enfants a {school_name} :"
    ]
    if not children:
        lines.append("Aucun enfant inscrit n'est associé à votre numéro pour le moment.")
    for child in children:
        moyenne = (
            f"{child.general_average}/20" if child.general_average is not None else "non calculée"
        )
        reste = _fmt_amount(child.fees_remaining)
        lines.append(
            f"- {child.full_name} ({child.class_name}) : moyenne {moyenne}, "
            f"{child.total_absences} absence(s), reste a payer {reste} FCFA"
        )
    lines.append("Pour le detail, connectez-vous a votre espace parent KLASSCI.")
    return "\n".join(lines)


async def handle_inbound(
    db: AsyncSession, *, raw_phone: str, text: str, provided_secret: str | None
) -> tuple[int, MailPulseInboundResult]:
    """Traite un message entrant. Retourne (status_http, résultat)."""
    school = await admin_service.get_school_settings(db)

    # Secret non configuré → on cache l'endpoint (404). Secret erroné → 401.
    if not school.mailpulse_inbound_secret:
        return 404, MailPulseInboundResult(status="disabled")
    if not verify_secret(school, provided_secret):
        return 401, MailPulseInboundResult(status="disabled")

    if not school.mailpulse_enabled:
        return 200, MailPulseInboundResult(status="disabled")

    if not text.strip().upper().startswith("INFO"):
        return 200, MailPulseInboundResult(status="ignored")

    client = build_client(school)
    if client is None:
        return 200, MailPulseInboundResult(status="disabled")

    phone = raw_phone.strip()
    parent = await _find_parent_by_phone(db, phone)
    if parent is None:
        await client.send_message(channel="whatsapp", recipient=phone, body=_UNKNOWN_NUMBER_REPLY)
        logger.info("mailpulse inbound INFO from unknown number")
        return 200, MailPulseInboundResult(status="unknown_number")

    children = await parent_portal_service.build_child_summaries(db, parent)
    reply = _compose_info_reply(parent, children, school)
    result = await client.send_message(
        channel="whatsapp",
        recipient=phone,
        body=reply,
        external_event_id=f"info-{parent.id}",
    )
    logger.info(
        "mailpulse inbound INFO replied parent_id=%s status=%s children=%s",
        parent.id,
        result.status,
        len(children),
    )
    return 200, MailPulseInboundResult(status="replied", matched=True)
