"""Router DREN stats — statistiques agrégées pour les rapports DREN."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db, require_permission
from app.schemas.dren_stats import DrenExportResponse, DrenStatsResponse
from app.services import dren_stats_service as service

router = APIRouter(prefix="/reports/dren-stats", tags=["reports"])


@router.get("/{academic_year_id}", response_model=DrenStatsResponse)
async def get_dren_stats(
    academic_year_id: int,
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Statistiques DREN complètes pour une année scolaire."""
    return await service.get_dren_stats(db, academic_year_id)


@router.get("/{academic_year_id}/export", response_model=DrenExportResponse)
async def export_dren_stats(
    academic_year_id: int,
    _: None = require_permission("reports:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Export des statistiques DREN (placeholder)."""
    return await service.export_dren_stats(db, academic_year_id)
