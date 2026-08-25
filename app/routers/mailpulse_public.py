"""Webhook public MailPulse — messages WhatsApp entrants (feature INFO).

Route NON authentifiée : le tenant est porté par l'URL (résolu par le
TenantMiddleware). L'authenticité est garantie par un secret partagé présenté
dans l'en-tête `X-MailPulse-Token`, comparé au secret configuré par le tenant.
"""

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db
from app.schemas.mailpulse import MailPulseInboundPayload
from app.services.mailpulse import inbound_service

router = APIRouter(prefix="/public/mailpulse", tags=["mailpulse-public"])

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


@router.post("/inbound/{tenant}")
async def inbound_message(
    tenant: str,
    payload: MailPulseInboundPayload,
    x_mailpulse_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    """Reçoit un message entrant relayé par MailPulse et répond « INFO » si demandé."""
    phone = payload.resolved_phone()
    text = payload.message_text()
    if not phone:
        return JSONResponse(
            status_code=422,
            content={"detail": "Numéro expéditeur manquant", "code": "MISSING_SENDER"},
            headers=_NOINDEX,
        )

    status_code, result = await inbound_service.handle_inbound(
        db, raw_phone=phone, text=text, provided_secret=x_mailpulse_token
    )
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(),
        headers=_NOINDEX,
    )
