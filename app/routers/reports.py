"""Router reports — generation et consultation des bulletins scolaires."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.reports import (
    BulletinGenerateRequest,
    BulletinGenerateResponse,
    BulletinListResponse,
)
from app.services import reports_service as service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post(
    "/bulletins/generate",
    response_model=BulletinGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_bulletins(
    data: BulletinGenerateRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("reports:generate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Genere les bulletins pour une classe et un trimestre."""
    return await service.generate_bulletins(
        db,
        class_id=data.class_id,
        trimester=data.trimester,
        academic_year_id=data.academic_year_id,
        generated_by=current_user.user_id,
    )


@router.get(
    "/bulletins/{class_id}/{trimester}",
    response_model=BulletinListResponse,
)
async def list_bulletins(
    class_id: int,
    trimester: int,
    academic_year_id: int = Query(...),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Liste les bulletins generes pour une classe/trimestre."""
    return await service.list_bulletins(db, class_id, trimester, academic_year_id)


@router.get("/bulletins/{bulletin_id}/pdf")
async def get_bulletin_pdf(
    bulletin_id: int,
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere et retourne le PDF d'un bulletin."""
    pdf_bytes = await service.get_bulletin_pdf(db, bulletin_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="bulletin_{bulletin_id}.pdf"'},
    )


@router.post("/bulletins/publish")
async def publish_bulletins(
    class_id: int = Query(...),
    trimester: int = Query(..., ge=1, le=3),
    academic_year_id: int = Query(...),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("reports:generate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Publie les bulletins d'une classe/trimestre (is_published=True)."""
    count = await service.publish_bulletins(
        db, class_id, trimester, academic_year_id, published_by=current_user.user_id
    )
    return {"published": count}
