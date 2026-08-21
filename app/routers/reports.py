"""Router reports — generation et consultation des bulletins scolaires."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_read import audit_read
from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    has_permission,
    require_permission,
)
from app.core.exceptions import NotFoundError
from app.routers._pdf_helpers import pdf_response
from app.schemas.reports import (
    BulletinGenerateRequest,
    BulletinGenerateResponse,
    BulletinListResponse,
    BulletinResponse,
)
from app.services import (
    class_synthesis_service,
    document_release_service,
    grade_report_service,
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
    "/bulletins",
    response_model=BulletinListResponse,
)
async def list_bulletins(
    class_id: int | None = Query(None),
    trimester: int | None = Query(None, ge=1, le=3),
    academic_year_id: int | None = Query(None),
    is_published: bool | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Liste paginee des bulletins, filtrable par classe, trimestre, annee et statut."""
    return await service.list_bulletins(
        db,
        class_id=class_id,
        trimester=trimester,
        academic_year_id=academic_year_id,
        is_published=is_published,
        page=page,
        size=size,
    )


@router.get("/bulletins/{bulletin_id}", response_model=BulletinResponse)
async def get_bulletin(
    bulletin_id: int,
    _read: None = audit_read("bulletin", param="bulletin_id"),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Retourne un bulletin par identifiant."""
    bulletin = await service.get_bulletin_response(db, bulletin_id)
    if bulletin is None:
        raise NotFoundError("Bulletin", bulletin_id)
    return bulletin


@router.get("/bulletins/{bulletin_id}/pdf")
async def get_bulletin_pdf(
    bulletin_id: int,
    _read: None = audit_read("bulletin", param="bulletin_id"),
    override_reason: str | None = Query(
        None,
        description="Motif de derogation. Requis pour delivrer malgre un impaye.",
        max_length=500,
    ),
    current_user: TokenData = Depends(get_current_user),
    may_override: bool = has_permission("documents:release:override"),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere et retourne le PDF d'un bulletin."""
    await document_release_service.ensure_bulletin_releasable(
        db,
        bulletin_id,
        actor_id=current_user.user_id,
        may_override=may_override,
        override_reason=override_reason,
    )
    return await pdf_response(
        lambda: service.get_bulletin_pdf(db, bulletin_id),
        filename=f"bulletin_{bulletin_id}.pdf",
        error_context=f"bulletin {bulletin_id}",
    )


@router.get("/classes/{class_id}/synthesis")
async def get_class_synthesis_pdf(
    class_id: int,
    trimester: int = Query(..., ge=1, le=3),
    academic_year_id: int = Query(...),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le rapport de synthèse d'une classe pour un trimestre (conseil de classe)."""
    return await pdf_response(
        lambda: class_synthesis_service.get_class_synthesis_pdf(
            db, class_id, trimester=trimester, academic_year_id=academic_year_id
        ),
        filename=f"synthese_classe_{class_id}_T{trimester}.pdf",
        error_context=f"class synthesis {class_id}",
    )


@router.get("/classes/{class_id}/grade-report")
async def get_class_grade_report_pdf(
    class_id: int,
    subject_id: int = Query(...),
    trimester: int = Query(..., ge=1, le=3),
    academic_year_id: int = Query(...),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Relevé de notes rempli d'une (classe, matière, trimestre) — moyennes + rangs."""
    return await pdf_response(
        lambda: grade_report_service.get_grade_report_pdf(
            db, class_id, subject_id, trimester, academic_year_id
        ),
        filename=f"releve-notes-{class_id}-S{subject_id}-T{trimester}.pdf",
        error_context=f"relevé de notes classe {class_id}",
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
    return {
        "message": f"{count} bulletin(s) publie(s)",
        "count": count,
    }
