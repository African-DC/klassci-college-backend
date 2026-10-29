"""Platform support console: explicit tenant selector; no accidental cross-school data mixing."""

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import tenant_database_url
from app.core.dependencies import require_permission
from app.core.slug import is_valid_tenant_slug
from app.schemas.support_incident import (
    IncidentOut,
    IncidentPage,
    IncidentReply,
    IncidentStatus,
    IncidentUpdate,
)
from app.services import support_incidents as service
from app.services.tenants._engine import short_lived_engine

router = APIRouter(prefix="/incidents", tags=["super-admin"])


def _validated(slug: str) -> str:
    if not is_valid_tenant_slug(slug):
        raise HTTPException(status_code=400, detail="Établissement invalide")
    return slug


@router.get("", response_model=IncidentPage)
async def list_incidents(
    tenant: str = Query(...),
    reference: str | None = Query(None, pattern=r"^[0-9A-Fa-f]{6,16}$"),
    status: IncidentStatus | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("super-admin:logs:read"),
) -> IncidentPage:
    async with short_lived_engine(
        tenant_database_url(_validated(tenant)), pool_pre_ping=True
    ) as engine:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await service.list_page(
                db, actor_id=None, reference=reference, status=status, page=page, size=size
            )


@router.get("/{tenant}/{incident_id}", response_model=IncidentOut)
async def get_incident(
    tenant: str,
    incident_id: str,
    _: None = require_permission("super-admin:logs:read"),
) -> IncidentOut:
    async with short_lived_engine(
        tenant_database_url(_validated(tenant)), pool_pre_ping=True
    ) as engine:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await service.get(db, incident_id, actor_id=None)


@router.patch("/{tenant}/{incident_id}", response_model=IncidentOut)
async def update_incident(
    tenant: str,
    incident_id: str,
    data: IncidentUpdate,
    _: None = require_permission("super-admin:logs:read"),
) -> IncidentOut:
    async with short_lived_engine(
        tenant_database_url(_validated(tenant)), pool_pre_ping=True
    ) as engine:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await service.update(db, incident_id, data)


@router.post("/{tenant}/{incident_id}/replies", response_model=IncidentOut)
async def reply(
    tenant: str,
    incident_id: str,
    data: IncidentReply,
    _: None = require_permission("super-admin:logs:read"),
) -> IncidentOut:
    async with short_lived_engine(
        tenant_database_url(_validated(tenant)), pool_pre_ping=True
    ) as engine:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await service.reply(
                db, incident_id, data, actor_id=0, actor_kind="support", owner_only=False
            )
