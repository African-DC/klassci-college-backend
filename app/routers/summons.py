"""Convocations de parents : émission, registre, suite donnée, document."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.school_life import (
    ParentSummonsCreate,
    ParentSummonsRegister,
    ParentSummonsResponse,
    SummonsOutcomeUpdate,
)
from app.services._document_verification_helper import render_verification
from app.services.pdf import generate_parent_summons_pdf
from app.services.school_life import summons_service

router = APIRouter(prefix="/school-life/summons", tags=["school-life", "summons"])


@router.post("", response_model=ParentSummonsResponse, status_code=201)
async def create_summons(
    data: ParentSummonsCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("documents:parent-summons"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentSummonsResponse:
    """Convoque le tuteur d'un élève et inscrit la convocation au registre."""
    return await summons_service.create_summons(db, data, actor_id=current_user.user_id)


@router.get("", response_model=ParentSummonsRegister)
async def list_summons(
    academic_year_id: int | None = Query(None),
    trimester: int | None = Query(None, ge=1, le=3),
    student_id: int | None = Query(None),
    outcome: str | None = Query(None, description="pending, attended ou missed"),
    _: None = require_permission("documents:parent-summons"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentSummonsRegister:
    """Registre des convocations : qui a été convoqué, et qui est venu."""
    return await summons_service.list_register(
        db,
        academic_year_id=academic_year_id,
        trimester=trimester,
        student_id=student_id,
        outcome=outcome,
    )


@router.get("/{summons_id}", response_model=ParentSummonsResponse)
async def get_summons(
    summons_id: int,
    _: None = require_permission("documents:parent-summons"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentSummonsResponse:
    return await summons_service.get_summons(db, summons_id)


@router.patch("/{summons_id}/outcome", response_model=ParentSummonsResponse)
async def record_summons_outcome(
    summons_id: int,
    data: SummonsOutcomeUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("documents:parent-summons"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ParentSummonsResponse:
    """Note si le tuteur s'est présenté au rendez-vous."""
    return await summons_service.record_outcome(db, summons_id, data, actor_id=current_user.user_id)


@router.get("/{summons_id}/document.pdf", summary="Convocation de parent (PDF)")
async def get_summons_document(
    summons_id: int,
    _: None = require_permission("documents:parent-summons"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Imprime la convocation, scellée pour être vérifiable au guichet."""
    data = await summons_service.compose_document_data(db, summons_id)
    settings = data["school_settings"]

    async def _generate() -> bytes:
        return await render_verification(
            db,
            data["verification"],
            lambda: generate_parent_summons_pdf(data, settings),
        )

    return await pdf_response(
        _generate,
        filename=f"convocation-{data['student_last_name']}-{summons_id}.pdf",
        error_context=f"convocation {summons_id}",
    )
