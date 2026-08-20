"""Router audit — le journal de ce qui s'est passé dans l'établissement."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, has_permission
from app.schemas.audit import AuditFiltersResponse, AuditListResponse
from app.services import audit as service

router = APIRouter(prefix="/admin/audit", tags=["audit"])

# Deux permissions, une seule route : le périmètre visible se déduit des
# droits détenus, il n'y a pas d'endpoint « comptable » séparé à maintenir
# en parallèle de l'endpoint direction.
_FULL = "audit:read"
_FINANCIAL = "audit:read:financial"


@router.get("/filters", response_model=AuditFiltersResponse)
async def get_audit_filters(
    full_access: bool = has_permission(_FULL),
    financial_access: bool = has_permission(_FINANCIAL),
    db: AsyncSession = Depends(get_tenant_db),
) -> AuditFiltersResponse:
    """Entités, actions et personnes réellement présentes dans le journal visible."""
    return await service.get_filters(db, full_access=full_access, financial_access=financial_access)


@router.get("", response_model=AuditListResponse)
async def list_audit(
    entity_type: str | None = Query(None, max_length=100),
    entity_id: int | None = Query(None, ge=1),
    action: str | None = Query(None, max_length=20),
    user_id: int | None = Query(None, ge=1),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    full_access: bool = has_permission(_FULL),
    financial_access: bool = has_permission(_FINANCIAL),
    db: AsyncSession = Depends(get_tenant_db),
) -> AuditListResponse:
    """Journal filtrable, du plus récent au plus ancien."""
    return await service.list_journal(
        db,
        full_access=full_access,
        financial_access=financial_access,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        page=page,
        size=size,
    )
