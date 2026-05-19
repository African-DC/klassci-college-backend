"""Router pointage enseignant (Phase 7b).

Endpoints :
- POST   /admin/teachers/{teacher_id}/attendance         — admin/staff saisit
- GET    /admin/teachers/{teacher_id}/attendance         — liste filtrée
- GET    /admin/teachers/{teacher_id}/attendance/stats   — KPIs AY
- PATCH  /admin/teacher-attendance/{attendance_id}/validate — valide auto-décl
- DELETE /admin/teacher-attendance/{attendance_id}       — annulation admin
- POST   /teacher/attendance/self-declare                — prof se déclare
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    require_permission,
)
from app.schemas.teacher_attendance import (
    TeacherAttendanceCreate,
    TeacherAttendanceListResponse,
    TeacherAttendanceResponse,
    TeacherAttendanceStats,
    TeacherAttendanceValidate,
    TeacherSelfDeclareCreate,
)
from app.services import teacher_attendance_service as service

admin_router = APIRouter(prefix="/admin", tags=["teacher-attendance"])
teacher_router = APIRouter(prefix="/teacher", tags=["teacher-attendance"])


# ---------------------------------------------------------------------------
# Admin / staff endpoints
# ---------------------------------------------------------------------------


@admin_router.post(
    "/teachers/{teacher_id}/attendance",
    response_model=TeacherAttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_record_attendance(
    teacher_id: int,
    data: TeacherAttendanceCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:attendance"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Saisie d'un pointage par admin/staff (validé immédiatement)."""
    return await service.record_attendance(
        db, teacher_id, data, declared_by_user_id=current_user.user_id
    )


@admin_router.get(
    "/teachers/{teacher_id}/attendance",
    response_model=TeacherAttendanceListResponse,
)
async def admin_list_attendance(
    teacher_id: int,
    academic_year_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    date_from: date_type | None = Query(None),
    date_to: date_type | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    _: None = require_permission("admin:teachers:attendance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Liste filtrée des pointages d'un enseignant."""
    return await service.list_for_teacher(
        db,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        page=page,
        per_page=per_page,
    )


@admin_router.get(
    "/teachers/{teacher_id}/attendance/stats",
    response_model=TeacherAttendanceStats,
)
async def admin_get_stats(
    teacher_id: int,
    academic_year_id: int | None = Query(None),
    _: None = require_permission("admin:teachers:attendance:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """KPIs agrégés pour la fiche teacher 360° tab Présences."""
    return await service.compute_stats(db, teacher_id=teacher_id, academic_year_id=academic_year_id)


@admin_router.patch(
    "/teacher-attendance/{attendance_id}/validate",
    response_model=TeacherAttendanceResponse,
)
async def admin_validate_attendance(
    attendance_id: int,
    data: TeacherAttendanceValidate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:attendance"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Valide ou rejette une auto-déclaration prof."""
    return await service.validate_attendance(
        db, attendance_id, data, validated_by_user_id=current_user.user_id
    )


@admin_router.delete(
    "/teacher-attendance/{attendance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def admin_delete_attendance(
    attendance_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:teachers:attendance"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Annulation totale d'un pointage (admin uniquement)."""
    await service.delete_attendance(db, attendance_id, deleted_by_user_id=current_user.user_id)


# ---------------------------------------------------------------------------
# Teacher portal endpoint — auto-déclaration
# ---------------------------------------------------------------------------


@teacher_router.post(
    "/attendance/self-declare",
    response_model=TeacherAttendanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def teacher_self_declare(
    data: TeacherSelfDeclareCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("teacher:attendance:self_declare"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Any:
    """Le prof se déclare absent/en retard — en attente de validation admin."""
    return await service.self_declare(db, teacher_user_id=current_user.user_id, data=data)
