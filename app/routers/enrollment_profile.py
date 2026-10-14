"""Router inscriptions — fiche de renseignements et bourse.

Inclus AVANT `enrollments.py` dans `main.py`, par principe : `/profiles/batch`
est un chemin littéral, et aucun paramètre ne doit pouvoir l'avaler.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.enrollment import EnrollmentResponse
from app.schemas.enrollment_profile import (
    EnrollmentProfileBatchRequest,
    EnrollmentProfileBatchResponse,
    EnrollmentProfileUpdate,
    ScholarshipSummary,
    ScholarshipUpsert,
)
from app.schemas.fee_discount import DiscountInput, DiscountLine
from app.services import enrollment_profile_update, enrollment_scholarship, fee_discount

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.patch(
    "/profiles/batch",
    response_model=EnrollmentProfileBatchResponse,
    summary="Renseigner la fiche de plusieurs inscriptions d'un coup",
)
async def update_profiles_in_batch(
    payload: EnrollmentProfileBatchRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentProfileBatchResponse:
    """Tout le lot ou rien : un 422 nomme chaque inscription fautive."""
    result = await enrollment_profile_update.update_profiles_in_batch(
        db, payload, updated_by=current_user.user_id
    )
    return EnrollmentProfileBatchResponse(**result)


@router.patch("/{enrollment_id}/profile", response_model=EnrollmentResponse)
async def update_profile(
    enrollment_id: int,
    data: EnrollmentProfileUpdate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> EnrollmentResponse:
    """Corrige la fiche. Un champ absent reste, un champ envoyé à `null` s'efface."""
    return await enrollment_profile_update.update_profile(
        db, enrollment_id, data, updated_by=current_user.user_id
    )


@router.put("/{enrollment_id}/scholarship", response_model=ScholarshipSummary)
async def put_scholarship(
    enrollment_id: int,
    data: ScholarshipUpsert,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("scholarships:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScholarshipSummary:
    """Pose la bourse de l'inscription, ou remplace celle qui existe."""
    return await enrollment_scholarship.upsert_scholarship(
        db, enrollment_id, data, actor=current_user.user_id
    )


@router.delete("/{enrollment_id}/scholarship", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scholarship(
    enrollment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("scholarships:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Retire la bourse. Sans bourse, répond 204 sans rien écrire."""
    await enrollment_scholarship.delete_scholarship(db, enrollment_id, actor=current_user.user_id)


@router.get("/{enrollment_id}/fee-discounts", response_model=list[DiscountLine])
async def get_enrollment_fee_discounts(
    enrollment_id: int,
    _: None = require_permission("fees:discount:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[DiscountLine]:
    return await fee_discount.list_discounts(db, enrollment_id)


@router.put("/{enrollment_id}/fee-discounts/{fee_id}", response_model=DiscountLine)
async def put_enrollment_fee_discount(
    enrollment_id: int, fee_id: int, data: DiscountInput,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("fees:discount:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> DiscountLine:
    return await fee_discount.set_discount(
        db, enrollment_id, fee_id, data, actor=current_user.user_id
    )


@router.delete("/{enrollment_id}/fee-discounts/{fee_id}", response_model=DiscountLine)
async def delete_enrollment_fee_discount(
    enrollment_id: int, fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("fees:discount:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> DiscountLine:
    return await fee_discount.set_discount(
        db, enrollment_id, fee_id, None, actor=current_user.user_id
    )
