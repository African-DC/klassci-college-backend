"""Router DREN stats — statistiques agrégées pour les rapports DREN."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.routers._pdf_helpers import binary_response, pdf_response
from app.schemas.dren_stats import DrenStatsResponse
from app.services import dren_stats_service as service

router = APIRouter(prefix="/reports/dren-stats", tags=["reports"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/{academic_year_id}", response_model=DrenStatsResponse)
async def get_dren_stats(
    academic_year_id: int,
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Statistiques DREN complètes pour une année scolaire."""
    return await service.get_dren_stats(db, academic_year_id)


@router.get("/{academic_year_id}/export")
async def export_dren_stats(
    academic_year_id: int,
    export_format: str = Query("pdf", alias="format", pattern="^(pdf|xlsx)$"),
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Exporte les statistiques DREN au format PDF (défaut) ou Excel (`?format=xlsx`)."""
    if export_format == "xlsx":
        # Meme filet que le PDF : sans lui, une erreur d'openpyxl remonte en
        # texte brut et le telechargement echoue en silence.
        return await binary_response(
            lambda: service.export_dren_stats_xlsx(db, academic_year_id),
            filename=f"statistiques-dren-{academic_year_id}.xlsx",
            media_type=_XLSX_MEDIA_TYPE,
            error_context=f"statistiques DREN {academic_year_id}",
            disposition="attachment",
        )
    return await pdf_response(
        lambda: service.export_dren_stats_pdf(db, academic_year_id),
        filename=f"statistiques-dren-{academic_year_id}.pdf",
        error_context=f"statistiques DREN {academic_year_id}",
        disposition="attachment",
    )
