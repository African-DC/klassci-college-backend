"""Router MailPulse — configuration des notifications email + WhatsApp (admin)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.mailpulse import (
    MailPulseConfigResponse,
    MailPulseConfigUpdate,
    MailPulseTestRequest,
    MailPulseTestResponse,
)
from app.services.mailpulse import settings_service, test_service

router = APIRouter(prefix="/admin/settings", tags=["mailpulse"])


@router.get("/mailpulse", response_model=MailPulseConfigResponse)
async def get_mailpulse_config(
    _: None = require_permission("mailpulse:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> MailPulseConfigResponse:
    """Retourne la configuration MailPulse du tenant (sans la clé API en clair)."""
    return await settings_service.get_config(db)


@router.put("/mailpulse", response_model=MailPulseConfigResponse)
async def update_mailpulse_config(
    data: MailPulseConfigUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("mailpulse:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> MailPulseConfigResponse:
    """Met à jour la configuration MailPulse. Clé API vide = conservée."""
    return await settings_service.update_config(db, data, updated_by=current_user.user_id)


@router.post("/mailpulse/test", response_model=MailPulseTestResponse)
async def send_mailpulse_test(
    data: MailPulseTestRequest,
    _: None = require_permission("mailpulse:test"),
    db: AsyncSession = Depends(get_tenant_db),
) -> MailPulseTestResponse:
    """Envoie une notification de test vers les destinataires DE TEST uniquement.

    Aucun vrai parent n'est impliqué. En mode simulation (dry-run), rien n'est
    réellement émis.
    """
    return await test_service.send_test(
        db, event=data.event, channel=data.channel, dry_run=data.dry_run
    )
