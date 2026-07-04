"""Router MailPulse — configuration des notifications email + WhatsApp (admin)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.mailpulse import MailPulseConfigResponse, MailPulseConfigUpdate
from app.services.mailpulse import settings_service

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
