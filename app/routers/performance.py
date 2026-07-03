"""Router — score de performance enseignant + activité personnel.

- `/admin/performance/*` : vue direction (permission `performance:read`).
- `/teacher/performance/me` : vue « Ma performance » de l'enseignant connecté.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    require_permission,
)
from app.schemas.performance import (
    StaffActivityListResponse,
    TeacherPerformanceListResponse,
    TeacherSelfPerformanceResponse,
)
from app.services import performance_service

admin_router = APIRouter(prefix="/admin/performance", tags=["performance"])
teacher_router = APIRouter(prefix="/teacher/performance", tags=["performance"])


@admin_router.get("/teachers", response_model=TeacherPerformanceListResponse)
async def list_teacher_performance(
    _: None = require_permission("performance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Score de performance de tous les enseignants (3 axes transparents)."""
    return await performance_service.get_teachers_performance(db)


@admin_router.get("/staff", response_model=StaffActivityListResponse)
async def list_staff_activity(
    _: None = require_permission("performance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Tableau d'activité du personnel (paiements encaissés, inscriptions)."""
    return await performance_service.get_staff_activity(db)


@teacher_router.get("/me", response_model=TeacherSelfPerformanceResponse)
async def get_my_performance(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Ma performance — l'enseignant connecté voit son propre score détaillé."""
    return await performance_service.get_teacher_self_performance(db, current_user.user_id)
