"""Router conseil de classe — PV et decisions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.council import (
    CouncilMinutesGenerateRequest,
    CouncilMinutesResponse,
    CouncilStudentDecisionResponse,
    DecisionOverrideRequest,
)
from app.services import council_service as service

router = APIRouter(prefix="/reports/council-minutes", tags=["council-minutes"])


@router.post("/generate", response_model=CouncilMinutesResponse, status_code=201)
async def generate_council_minutes(
    data: CouncilMinutesGenerateRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("reports:generate"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Genere le PV du conseil de classe pour une classe/trimestre."""
    return await service.generate_council_minutes(db, data, generated_by=current_user.user_id)


@router.get("/{class_id}/{trimester}", response_model=CouncilMinutesResponse)
async def get_council_minutes(
    class_id: int,
    trimester: int,
    academic_year_id: int = Query(...),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Retourne le PV du conseil de classe."""
    return await service.get_council_minutes(db, class_id, trimester, academic_year_id)


@router.get("/{class_id}/{trimester}/pdf")
async def get_council_minutes_pdf(
    class_id: int,
    trimester: int,
    academic_year_id: int = Query(...),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere et retourne le PDF du PV du conseil de classe."""
    pdf_bytes = await service.get_council_minutes_pdf(db, class_id, trimester, academic_year_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'inline; filename="pv_conseil_{class_id}_T{trimester}.pdf"')
        },
    )


@router.patch(
    "/decisions/{decision_id}",
    response_model=CouncilStudentDecisionResponse,
)
async def override_decision(
    decision_id: int,
    data: DecisionOverrideRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("reports:override"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Override la decision automatique pour un eleve."""
    return await service.override_decision(
        db, decision_id, data, overridden_by=current_user.user_id
    )
