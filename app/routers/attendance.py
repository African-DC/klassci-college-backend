"""Router presences — CRUD /attendance."""

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.attendance import (
    ClassAttendanceStats,
    SessionCreate,
    SessionResponse,
    SessionUpdate,
    StudentAttendanceResponse,
)
from app.services import attendance_service

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("attendance:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SessionResponse:
    """Cree une session de pointage avec les records pour tous les eleves."""
    return await attendance_service.create_session(db, data, created_by=current_user.user_id)


@router.patch("/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: int,
    data: SessionUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("attendance:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> SessionResponse:
    """Met a jour les records d'une session de pointage."""
    return await attendance_service.update_session(
        db, session_id, data, updated_by=current_user.user_id
    )


@router.get("/student/{student_id}", response_model=StudentAttendanceResponse)
async def get_student_attendance(
    student_id: int,
    status_filter: str | None = Query(None, alias="status"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("attendance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> StudentAttendanceResponse:
    """Retourne l'historique de presence d'un eleve avec pagination."""
    return await attendance_service.get_student_attendance(
        db,
        student_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )


@router.get("/class/{class_id}/stats", response_model=ClassAttendanceStats)
async def get_class_stats(
    class_id: int,
    academic_year_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _: None = require_permission("attendance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ClassAttendanceStats:
    """Retourne les statistiques de presence pour une classe."""
    return await attendance_service.get_class_stats(
        db,
        class_id,
        academic_year_id=academic_year_id,
        date_from=date_from,
        date_to=date_to,
    )
