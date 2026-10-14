"""Frais d'inscription : réduction individuelle, avec permissions dédiées."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    require_permission,
)
from app.schemas.fee_discount import FeeDiscountResponse, FeeDiscountUpsert
from app.services import fee_discounts

router = APIRouter(prefix="/enrollments", tags=["fee-discounts"])


@router.get("/{enrollment_id}/discounts", response_model=list[FeeDiscountResponse])
async def list_enrollment_discounts(
    enrollment_id: int,
    _: None = require_permission("discounts:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[FeeDiscountResponse]:
    """Les décisions déjà accordées sur une inscription précise."""
    return await fee_discounts.list_discounts(db, enrollment_id)


@router.put(
    "/{enrollment_id}/fees/{fee_id}/discount", response_model=FeeDiscountResponse,
)
async def upsert_enrollment_fee_discount(
    enrollment_id: int,
    fee_id: int,
    data: FeeDiscountUpsert,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("discounts:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> FeeDiscountResponse:
    """Accorder ou corriger une remise, sans réécrire les versements."""
    return await fee_discounts.set_discount(
        db, enrollment_id, fee_id, data, actor=current_user.user_id,
    )


@router.delete(
    "/{enrollment_id}/fees/{fee_id}/discount",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_enrollment_fee_discount(
    enrollment_id: int,
    fee_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("discounts:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Annuler une remise et restaurer le montant initial, avec audit."""
    await fee_discounts.remove_discount(
        db, enrollment_id, fee_id, actor=current_user.user_id,
    )
