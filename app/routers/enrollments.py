"""Router inscriptions — CRUD /enrollments."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentListResponse,
    EnrollmentResponse,
    EnrollmentUpdate,
)
from app.services import enrollment_service

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.get("", response_model=EnrollmentListResponse)
async def list_enrollments(
    class_id: int | None = Query(None),
    status: str | None = Query(None),
    academic_year_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentListResponse:
    """Liste paginée des inscriptions avec filtres optionnels."""
    return await enrollment_service.list_enrollments(
        db,
        class_id=class_id,
        status=status,
        academic_year_id=academic_year_id,
        page=page,
        size=size,
    )


@router.post("", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    data: EnrollmentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Crée une nouvelle inscription."""
    return await enrollment_service.create_enrollment(db, data, created_by=current_user.user_id)


@router.get("/{enrollment_id}", response_model=EnrollmentResponse)
async def get_enrollment(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Retourne une inscription par ID."""
    return await enrollment_service.get_enrollment(db, enrollment_id)


@router.patch("/{enrollment_id}", response_model=EnrollmentResponse)
async def update_enrollment(
    enrollment_id: int,
    data: EnrollmentUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Met à jour le statut ou les notes d'une inscription (patch partiel)."""
    return await enrollment_service.update_enrollment(
        db, enrollment_id, data, updated_by=current_user.user_id
    )


@router.delete("/{enrollment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_enrollment(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:delete"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Supprime une inscription."""
    await enrollment_service.delete_enrollment(db, enrollment_id, deleted_by=current_user.user_id)
