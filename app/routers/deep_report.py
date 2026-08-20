"""Router du rapport de fin de trimestre de la DEEP."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.services import deep_report as service

router = APIRouter(prefix="/reports/deep-trimester", tags=["reports"])


@router.get("/{academic_year_id}")
async def export_deep_trimester_report(
    academic_year_id: int,
    trimester: int = Query(1, ge=1, le=3),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Rapport DEEP complet (27 tableaux) au format PDF.

    Téléchargement forcé : le document se dépose à la DRENA, il n'a pas
    vocation à être consulté dans un onglet.
    """
    return await pdf_response(
        lambda: service.build_report_pdf(db, academic_year_id, trimester),
        filename=f"rapport-deep-trimestre-{trimester}-{academic_year_id}.pdf",
        error_context=f"rapport DEEP trimestre {trimester} ({academic_year_id})",
        disposition="attachment",
    )
