"""Router paiements — CRUD /payments + bordereau journalier."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    TokenData,
    get_current_user,
    get_tenant_db,
    has_permission,
    require_permission,
)
from app.routers._pdf_helpers import pdf_response
from app.schemas.payment import (
    PaymentCreate,
    PaymentListResponse,
    PaymentResponse,
    PaymentSummaryResponse,
)
from app.services import daily_cash_book_service, payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=PaymentListResponse)
async def list_payments(
    status_filter: str | None = Query(None, alias="status"),
    method: str | None = Query(None),
    enrollment_fee_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentListResponse:
    """Liste paginée des paiements avec filtres optionnels.

    Un caissier n'a pas `payments:read:all` : il ne lit que les versements
    qu'il a lui-même encaissés.
    """
    return await payment_service.list_payments(
        db,
        status=status_filter,
        method=method,
        enrollment_fee_id=enrollment_fee_id,
        date_from=date_from,
        date_to=date_to,
        received_by=None if can_read_all else current_user.user_id,
        page=page,
        size=size,
    )


@router.post("", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    data: PaymentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Enregistre un nouveau paiement."""
    return await payment_service.create_payment(db, data, received_by=current_user.user_id)


# NOTE: /summary MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "summary" as a payment_id path param.
@router.get("/summary", response_model=PaymentSummaryResponse)
async def get_payments_summary(
    academic_year_id: int | None = Query(None),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentSummaryResponse:
    """Agrège les statistiques de paiement (total attendu, payé, en attente, annulé)."""
    return await payment_service.get_payments_summary(db, academic_year_id=academic_year_id)


# NOTE: /daily-cash-book MUST be defined BEFORE /{payment_id}
@router.get(
    "/daily-cash-book",
    summary="Bordereau journalier (PDF) — récap des versements d'une date",
)
async def get_daily_cash_book(
    target_date: date | None = Query(
        None,
        alias="date",
        description="Date à imprimer (YYYY-MM-DD). Par défaut : aujourd'hui.",
    ),
    current_user: TokenData = Depends(get_current_user),
    can_read_all: bool = has_permission("payments:read:all"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le bordereau journalier signé pour la comptabilité.

    Groupe les paiements de la date par méthode (espèces / mobile money /
    virement / chèque), total par méthode + total général, signatures
    Caissier / Comptabilité.

    Un caissier n'obtient que SA caisse : sans ce filtre, il imprimerait les
    encaissements de toute l'école. Le comptable, lui, obtient le document
    consolidé.
    """
    target = target_date or date.today()
    return await pdf_response(
        lambda: daily_cash_book_service.get_daily_cash_book_pdf(
            db,
            target,
            cashier_user_id=current_user.user_id,
            restrict_to_cashier=not can_read_all,
        ),
        filename=f"bordereau-{target.isoformat()}.pdf",
        error_context=f"bordereau journalier {target.isoformat()}",
    )


# NOTE: /student/{enrollment_id} MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "student" as a payment_id path param.
@router.get(
    "/student/{enrollment_id}",
    response_model=list[PaymentResponse],
)
async def get_student_payments(
    enrollment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[PaymentResponse]:
    """Retourne tous les paiements d'un élève via son enrollment."""
    return await payment_service.get_student_payments(db, enrollment_id)


# NOTE: /{payment_id}/receipt MUST be defined BEFORE /{payment_id}
# to avoid FastAPI matching "receipt" as part of a different route.
@router.get("/{payment_id}/receipt")
async def get_payment_receipt(
    payment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Genere et retourne le recu de paiement en PDF."""
    return await pdf_response(
        lambda: payment_service.get_payment_receipt_pdf(db, payment_id),
        filename=f"recu_{payment_id}.pdf",
        error_context=f"reçu paiement {payment_id}",
    )


@router.post("/{payment_id}/validate", response_model=PaymentResponse)
async def validate_payment(
    payment_id: int,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Valide un paiement (pending → completed)."""
    return await payment_service.validate_payment(db, payment_id, validated_by=current_user.user_id)


@router.post("/{payment_id}/cancel", response_model=PaymentResponse)
async def cancel_payment(
    payment_id: int,
    current_user: TokenData = Depends(get_current_user),
    may_cancel_any: bool = has_permission("payments:cancel:any"),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Annule un paiement.

    Le comptable corrige n'importe quel versement. Le caissier ne corrige que
    sa propre saisie, et seulement tant que sa journée n'est pas clôturée.
    """
    return await payment_service.cancel_payment(
        db,
        payment_id,
        cancelled_by=current_user.user_id,
        may_cancel_any=may_cancel_any,
    )


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Retourne un paiement par ID."""
    return await payment_service.get_payment(db, payment_id)
