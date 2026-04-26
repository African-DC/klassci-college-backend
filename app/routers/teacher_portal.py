"""Router portail enseignant — endpoints read-only /teacher."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.schemas.attendance import ClassAttendanceStats
from app.schemas.teacher_portal import (
    TeacherClassesListResponse,
    TeacherDashboardStats,
    TeacherScheduleResponse,
)
from app.services import teacher_portal_service

router = APIRouter(prefix="/teacher", tags=["teacher-portal"])


@router.get("/classes", response_model=TeacherClassesListResponse)
async def get_teacher_classes(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherClassesListResponse:
    """Retourne les classes assignées à l'enseignant connecté."""
    return await teacher_portal_service.get_classes(db, current_user.user_id)


@router.get("/schedule", response_model=TeacherScheduleResponse)
async def get_teacher_schedule(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherScheduleResponse:
    """Retourne l'emploi du temps personnel de l'enseignant connecté."""
    return await teacher_portal_service.get_schedule(db, current_user.user_id)


@router.get("/dashboard-stats", response_model=TeacherDashboardStats)
async def get_teacher_dashboard_stats(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> TeacherDashboardStats:
    """Retourne les KPIs du dashboard enseignant."""
    return await teacher_portal_service.get_dashboard_stats(db, current_user.user_id)


@router.get("/classes/{class_id}/attendance", response_model=ClassAttendanceStats)
async def get_class_attendance(
    class_id: int,
    academic_year_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassAttendanceStats:
    """Stats de presence pour une classe assignee a l'enseignant connecte."""
    return await teacher_portal_service.get_class_attendance(
        db,
        current_user.user_id,
        class_id,
        academic_year_id=academic_year_id,
        date_from=date_from,
        date_to=date_to,
    )
