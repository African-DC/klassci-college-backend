"""Router tranches — grille de l'établissement et échéancier d'une inscription."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.installment import (
    EnrollmentPlanUpdate,
    EnrollmentScheduleResponse,
    FeeInstallmentGridUpdate,
    FeeInstallmentResponse,
)
from app.services import installments as installment_service

router = APIRouter(tags=["installments"])


@router.get(
    "/admin/fee-installments",
    response_model=list[FeeInstallmentResponse],
    summary="Grille de tranches d'une année scolaire",
)
async def get_grid(
    academic_year_id: int = Query(..., description="Année scolaire concernée"),
    _: None = require_permission("admin:fee-installments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeInstallmentResponse]:
    """Découpage du total obligatoire en tranches, avec leurs échéances."""
    return await installment_service.list_grid(db, academic_year_id)


@router.put(
    "/admin/fee-installments",
    response_model=list[FeeInstallmentResponse],
    summary="Remplacer la grille de tranches d'une année",
)
async def put_grid(
    data: FeeInstallmentGridUpdate,
    academic_year_id: int = Query(..., description="Année scolaire concernée"),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("admin:fee-installments:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeInstallmentResponse]:
    """Remplacement intégral : la somme des pourcentages doit faire 100 %."""
    return await installment_service.replace_grid(
        db, academic_year_id, data, updated_by=current_user.user_id
    )


@router.get(
    "/enrollments/{enrollment_id}/schedule",
    response_model=EnrollmentScheduleResponse,
    summary="Échéancier applicable à une inscription et état de retard",
)
async def get_schedule(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentScheduleResponse:
    """Accord négocié s'il existe, sinon la grille de l'établissement."""
    return await installment_service.resolve_schedule(db, enrollment_id)


@router.put(
    "/enrollments/{enrollment_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Fixer un échéancier négocié avec la famille",
)
async def put_schedule(
    enrollment_id: int,
    data: EnrollmentPlanUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:schedule:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Le total doit correspondre exactement aux frais obligatoires."""
    await installment_service.set_enrollment_plan(
        db, enrollment_id, data, updated_by=current_user.user_id
    )


@router.delete(
    "/enrollments/{enrollment_id}/schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retirer l'échéancier négocié",
)
async def delete_schedule(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:schedule:write"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """La famille repasse sur la grille standard de l'établissement."""
    await installment_service.clear_enrollment_plan(
        db, enrollment_id, updated_by=current_user.user_id
    )
