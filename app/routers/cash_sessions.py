"""Router caisse — ma journée (caissier) et point journalier (comptable)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import current_business_date
from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.cash_session import (
    CashSessionCloseRequest,
    CashSessionListResponse,
    CashSessionRegularizeRequest,
    CashSessionResponse,
)
from app.services import cash_closure_service, cash_session_service, daily_cash_book_service

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
        db, current_user.user_id, business_date or current_business_date()
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
        db, current_user.user_id, business_date or current_business_date(), data
    )


@router.get(
    "/me/daily-cash-book",
    summary="Bordereau de ma caisse (PDF)",
)
async def get_my_daily_cash_book(
    business_date: date | None = Query(
        None,
        alias="date",
        description="Journée à imprimer (YYYY-MM-DD). Par défaut : aujourd'hui.",
    ),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("cash-session:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Pièce de la caisse connectée, jamais celle d'un collègue.

    Contrairement à `GET /payments/daily-cash-book`, la portée ne dépend pas
    de `payments:read:all` : un admin qui tient un guichet imprime ici SA
    caisse, pas le consolidé de l'école.
    """
    target = business_date or current_business_date()
    return await pdf_response(
        lambda: daily_cash_book_service.get_daily_cash_book_pdf(
            db,
            target,
            cashier_user_id=current_user.user_id,
            restrict_to_cashier=True,
        ),
        filename=f"bordereau-{target.isoformat()}.pdf",
        error_context=f"bordereau de caisse {target.isoformat()}",
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
    return await cash_session_service.get_daily_point(db, business_date or current_business_date())


# NOTE : littérales avant toute route paramétrique. `/me/to-regularize` et
# `/me/regularize` sont déclarées ici, après `/me` et `/me/close`, mais toutes
# restent avant la route racine et avant tout `/{id}` futur.
@router.get(
    "/me/to-regularize",
    response_model=list[CashSessionResponse],
    summary="Mes journées clôturées d'office, en attente de comptage",
)
async def list_my_sessions_to_regularize(
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("cash-session:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[CashSessionResponse]:
    """Ce que le caissier doit régulariser, à afficher dès sa connexion.

    Une liste vide est la réponse normale et attendue : la plupart des
    caissiers clôturent leur journée.
    """
    return await cash_closure_service.list_sessions_to_regularize(db, current_user.user_id)


@router.post(
    "/me/regularize",
    response_model=CashSessionResponse,
    summary="Régulariser une journée clôturée d'office",
)
async def regularize_my_cash_session(
    data: CashSessionRegularizeRequest,
    business_date: date = Query(
        ...,
        alias="date",
        description="Journée à régulariser (YYYY-MM-DD). Obligatoire : c'est une journée passée.",
    ),
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("cash-session:manage"),
    db: AsyncSession = Depends(get_tenant_db),
) -> CashSessionResponse:
    """Saisit après coup le montant compté et fait naître l'écart réel.

    L'écart se calcule contre le théorique figé la nuit de la clôture d'office,
    jamais contre un théorique recalculé aujourd'hui.
    """
    return await cash_closure_service.regularize_my_session(
        db, current_user.user_id, business_date, data
    )
