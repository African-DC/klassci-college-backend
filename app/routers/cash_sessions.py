"""Router caisse — ma journée (caissier) et point journalier (comptable)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.schemas.cash_session import (
    CashSessionCloseRequest,
    CashSessionListResponse,
    CashSessionResponse,
)
from app.services import cash_session_service

router = APIRouter(prefix="/cash-sessions", tags=["cash-sessions"])


# NOTE : /me doit être déclaré AVANT toute route paramétrique du même router,
# sinon FastAPI tente de parser "me" comme un identifiant.
@router.get(
    "/me",
    response_model=CashSessionResponse,
    summary="Ma caisse — journée en cours du caissier connecté",
)
async def get_my_cash_session(
    business_date: date | None = Query(
        None,
        alias="date",
        description="Journée à consulter (YYYY-MM-DD). Par défaut : aujourd'hui.",
    ),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("cash-session:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> CashSessionResponse:
    """Ce que le caissier a encaissé aujourd'hui, ventilé par moyen de paiement."""
    return await cash_session_service.get_my_session(
        db, current_user.user_id, business_date or date.today()
    )


@router.post(
    "/me/close",
    response_model=CashSessionResponse,
    summary="Clôturer ma journée de caisse",
)
async def close_my_cash_session(
    data: CashSessionCloseRequest,
    business_date: date | None = Query(
        None, alias="date", description="Journée à clôturer (YYYY-MM-DD). Par défaut : aujourd'hui."
    ),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("cash-session:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> CashSessionResponse:
    """Fige le théorique espèces, calcule l'écart avec le montant compté, verrouille."""
    return await cash_session_service.close_my_session(
        db, current_user.user_id, business_date or date.today(), data
    )


@router.get(
    "",
    response_model=CashSessionListResponse,
    summary="Point journalier — toutes les caisses d'une date",
)
async def get_daily_point(
    business_date: date | None = Query(
        None,
        alias="date",
        description="Journée à consulter (YYYY-MM-DD). Par défaut : aujourd'hui.",
    ),
    _: None = require_permission("cash-session:read:all"),
    db: AsyncSession = Depends(get_tenant_db),
) -> CashSessionListResponse:
    """Vue comptable : chaque caisse, son total, son écart, son état de clôture."""
    return await cash_session_service.get_daily_point(db, business_date or date.today())
