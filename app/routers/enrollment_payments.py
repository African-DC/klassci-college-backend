"""Router paiements d'inscription — POST/GET/preview /enrollments/{id}/payments.

Séparé du router `enrollments` (CRUD + documents) pour rester sous la
limite no-god-code et garder le sous-domaine paiement-caissier
identifiable au premier coup d'oeil.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenData, get_current_user, get_tenant_db, require_permission
from app.routers._pdf_helpers import pdf_response
from app.schemas.payment import (
    AllocationPreviewResponse,
    EnrollmentPaymentCreate,
    PaymentResponse,
)
from app.services import enrollment_form_service, fee_statement_service, payment_service

router = APIRouter(prefix="/enrollments", tags=["enrollments", "payments"])


@router.post(
    "/{enrollment_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un versement caissier (auto-allocation prioritaire)",
)
async def record_enrollment_payment(
    enrollment_id: int,
    data: EnrollmentPaymentCreate,
    current_user: TokenData = Depends(get_current_user),
    _: None = require_permission("payments:create"),
    db: AsyncSession = Depends(get_tenant_db),
) -> PaymentResponse:
    """Enregistre un versement sur une inscription, alloué automatiquement.

    Priorité catégorie ASC : Inscription → T1 → T2 → T3 → COGES → Tenue →
    reste. Si le montant dépasse la dette restante : 422.

    Le moyen de paiement doit être accepté par l'établissement ET autorisé pour
    le profil de l'appelant (`payments:method:*`) ; sinon 403 avec le détail de
    ce qu'il peut faire et de qui contacter. Seules les espèces exigent une
    journée de caisse ouverte.
    """
    return await payment_service.record_enrollment_payment(
        db, enrollment_id, data, actor=current_user
    )


@router.get(
    "/{enrollment_id}/payments",
    response_model=list[PaymentResponse],
    summary="Historique des paiements d'une inscription",
)
async def list_enrollment_payments(
    enrollment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> list[PaymentResponse]:
    """Liste les paiements d'une inscription, plus récent en premier."""
    return await payment_service.get_student_payments(db, enrollment_id)


@router.get(
    "/{enrollment_id}/payments/preview",
    response_model=AllocationPreviewResponse,
    summary="Preview de l'allocation d'un versement (UX caissier avant submit)",
)
async def preview_enrollment_payment(
    enrollment_id: int,
    amount: Decimal = Query(..., gt=0, description="Montant proposé en XOF"),
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> AllocationPreviewResponse:
    """Montre comment `amount` serait alloué sans rien écrire.

    Inclut le surplus et la raison de rejet si le montant excède la dette.
    Utilisé côté FE pour le bloc "Aperçu allocation" avant le click final.
    """
    return await payment_service.preview_allocation(db, enrollment_id, amount)


@router.get(
    "/{enrollment_id}/statement",
    summary="État individuel des frais (PDF premium pour parent / caissier)",
)
async def get_fee_statement_pdf(
    enrollment_id: int,
    _: None = require_permission("payments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère le PDF d'état des frais : KPIs + détail frais + historique versements.

    Document parent : Mariam Koné voit en un coup d'œil où elle en est sur
    l'année scolaire de son enfant (total dû, total versé, reste à payer,
    breakdown par catégorie + historique des versements).
    """
    return await pdf_response(
        lambda: fee_statement_service.get_fee_statement_pdf(db, enrollment_id),
        filename=f"etat-frais-{enrollment_id}.pdf",
        error_context=f"état des frais (inscription {enrollment_id})",
    )


@router.get(
    "/{enrollment_id}/form",
    summary="Fiche d'inscription officielle (PDF à signer parent + admin)",
)
async def get_enrollment_form_pdf(
    enrollment_id: int,
    _: None = require_permission("enrollments:read"),
    db: AsyncSession = Depends(get_tenant_db),
) -> Response:
    """Génère la fiche d'inscription officielle à signer par le parent.

    Bandeau République CI + identité élève (photo, naissance) + 3 blocs
    responsables (père/mère/tuteur) + tableau frais avec total + signatures
    Parent + Chef d'établissement.
    """
    return await pdf_response(
        lambda: enrollment_form_service.get_enrollment_form_pdf(db, enrollment_id),
        filename=f"fiche-inscription-{enrollment_id}.pdf",
        error_context=f"fiche d'inscription {enrollment_id}",
    )
