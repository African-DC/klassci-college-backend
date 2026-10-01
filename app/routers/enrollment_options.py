"""Router inscriptions — souscription aux options de frais facultatifs."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.enrollment import SubscribeOptionRequest
from app.services import enrollment_options

router = APIRouter(prefix="/enrollments", tags=["enrollments"])


@router.post(
    "/{enrollment_id}/options",
    status_code=status.HTTP_201_CREATED,
)
async def subscribe_option(
    enrollment_id: int,
    data: SubscribeOptionRequest,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict:
    """Souscrit un élève à une option de frais facultatif."""
    async with db.begin_nested():
        result = await enrollment_options.subscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            optional_fee_option_id=data.optional_fee_option_id,
            created_by=current_user.user_id,
        )
    await db.commit()
    return result


@router.delete(
    "/{enrollment_id}/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unsubscribe_option(
    enrollment_id: int,
    option_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("enrollments:update"),
    db: AsyncSession = Depends(get_tenant_db),
) -> None:
    """Désinscrit un élève d'une option de frais facultatif."""
    async with db.begin_nested():
        await enrollment_options.unsubscribe_optional_fee(
            db,
            enrollment_id=enrollment_id,
            option_id=option_id,
            deleted_by=current_user.user_id,
        )
    await db.commit()
