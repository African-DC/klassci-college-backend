"""Tenant-only support routes. Reporters see their own issues; school support permission widens scope."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    resolve_permission,
)
from app.schemas.support_incident import (
    IncidentCreate,
    IncidentOut,
    IncidentPage,
    IncidentReply,
    IncidentStatus,
)
from app.services import support_incidents as service

router = APIRouter(prefix="/support/incidents", tags=["support"])


async def _visibility(user: TokenData, db: AsyncSession) -> int | None:
    return None if await resolve_permission(user, db, "support:read") else user.user_id


@router.get("", response_model=IncidentPage)
async def list_incidents(
    reference: str | None = Query(None, pattern=r"^[0-9A-Fa-f]{6,16}$"),
    status: IncidentStatus | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> IncidentPage:
    return await service.list_page(
        db,
        actor_id=await _visibility(user, db),
        reference=reference,
        status=status,
        page=page,
        size=size,
    )


@router.post("", response_model=IncidentOut, status_code=201)
async def create_incident(
    data: IncidentCreate,
    user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> IncidentOut:
    return await service.create(db, data, actor_id=user.user_id)


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(
    incident_id: str,
    user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> IncidentOut:
    return await service.get(db, incident_id, actor_id=await _visibility(user, db))


@router.post("/{incident_id}/replies", response_model=IncidentOut)
async def reply_to_incident(
    incident_id: str,
    data: IncidentReply,
    user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> IncidentOut:
    # School-wide readers are not automatically allowed to speak for the reporter.
    return await service.reply(
        db,
        incident_id,
        data,
        actor_id=user.user_id,
        actor_kind="school",
        owner_only=not await resolve_permission(user, db, "support:read"),
    )
