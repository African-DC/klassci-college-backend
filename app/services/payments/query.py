"""Read-only queries paiements : list, get, get_by_enrollment, summary."""

from dataclasses import replace

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.fee import Payment, PaymentStatus
from app.repositories import installment_repository
from app.repositories import payment_repository as repo
from app.repositories.payment_filters import (
    PaymentFilters,
    apply_payment_scope,
    belongs_to_year,
)
from app.schemas.payment import (
    PaymentListResponse,
    PaymentResponse,
    PaymentSummaryResponse,
)
from app.services import fees_paid
from app.services.payments._response import payment_to_response


async def list_payments(
    db: AsyncSession,
    *,
    filters: PaymentFilters,
    page: int = 1,
    size: int = 20,
) -> PaymentListResponse:
    """Retourne une page de paiements.

    Les critères sont composés par le routeur, qui y résout au passage la
    caisse que l'appelant a le droit de lire.
    """
    payments, total = await repo.list_payments(db, filters=filters, page=page, size=size)
    return PaymentListResponse(
        items=[payment_to_response(p) for p in payments],
        total=total,
        page=page,
        size=size,
    )


async def get_payment(db: AsyncSession, payment_id: int) -> PaymentResponse:
    """Retourne un paiement par ID ou lève 404."""
    payment = await repo.get_payment_with_allocations(db, payment_id)
    if payment is None:
        raise NotFoundError("Payment", payment_id)
    return payment_to_response(payment)


async def get_student_payments(db: AsyncSession, enrollment_id: int) -> list[PaymentResponse]:
    """Retourne tous les paiements liés à une inscription."""
    payments = await repo.get_payments_by_enrollment_id(db, enrollment_id)
    return [payment_to_response(p) for p in payments]


# Les tests historiques importent le prédicat depuis ici. Il vit désormais
# avec les autres critères du journal, pour que liste et bandeau ne puissent
# pas en avoir deux lectures.
_belongs_to_year = belongs_to_year


def _filtres_avec_annee(
    filters: PaymentFilters | None, academic_year_id: int | None
) -> PaymentFilters:
    """L'année du bandeau et celle des filtres sont la même question."""
    filtres = filters or PaymentFilters()
    if academic_year_id is not None and filtres.academic_year_id is None:
        return replace(filtres, academic_year_id=academic_year_id)
    return filtres


async def get_payments_summary(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
    received_by: int | None = None,
    filters: PaymentFilters | None = None,
) -> PaymentSummaryResponse:
    """Agrège les statistiques de paiement (KPIs dashboard admin).

    Deux périmètres cohabitent ici, et c'est délibéré :

    - **le recouvrement** — `total_expected`, `total_paid` et le taux qui en
      découle. Les deux moitiés parlent de la même dette : les frais
      obligatoires encore dus, et l'argent imputé sur eux. C'est le calcul de
      la fiche de l'élève et de l'échéancier, appliqué à toute l'école.
      Auparavant, l'attendu totalisait tous les frais — facultatifs et
      exonérés compris — face à une somme brute de versements : une famille
      exonérée après avoir versé restait comptée comme ayant payé, et le taux
      du tableau de bord contredisait la fiche de l'élève.

    - **la caisse** — `total_pending`, `total_cancelled` et le nombre de
      versements. Ce sont des versements, pas des dettes : on les compte tels
      qu'ils ont été enregistrés, versements orphelins compris, pour que le
      tableau de bord ne dise pas moins que le bordereau du jour. Aucun taux
      n'en est tiré : ils ne se comparent à aucun attendu.

    `received_by` ne restreint que la seconde moitié. Le recouvrement n'a pas
    de version « pour une personne » : il se lit sur les frais dus, pas sur
    qui a tenu le guichet. Pour un appelant cloisonné il n'est donc pas
    calculé du tout, et `total_paid` change de sens — ce qu'il a encaissé,
    et non ce que l'école a recouvré.
    """
    cloisonne = received_by is not None
    filtres = _filtres_avec_annee(filters, academic_year_id)
    annee = filtres.academic_year_id

    total_expected: float | None = None
    completion_rate: float | None = None
    if not cloisonne:
        total_expected = float(
            await installment_repository.mandatory_total_for_year(db, annee)
        )
        total_paid = float(await fees_paid.paid_on_mandatory_for_year(db, annee))
    else:
        encaisse_stmt = select(
            func.coalesce(
                func.sum(
                    case(
                        (Payment.status == PaymentStatus.COMPLETED.value, Payment.amount),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(Payment.received_by == received_by)
        # « Encaisse par vous » est un agregat de caisse, comme le compte
        # juste a cote : les deux doivent repondre a la meme question,
        # sinon la carte affiche un montant de l'annee sous un nombre
        # filtre, et affirme que le filtre vaut pour les deux.
        encaisse_stmt = await apply_payment_scope(db, encaisse_stmt, filtres)
        total_paid = float((await db.execute(encaisse_stmt)).scalar() or 0)

    pay_stmt = select(
        func.count().label("payment_count"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.status == PaymentStatus.PENDING.value, Payment.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_pending"),
        func.coalesce(
            func.sum(
                case(
                    (Payment.status == PaymentStatus.CANCELLED.value, Payment.amount),
                    else_=0,
                )
            ),
            0,
        ).label("total_cancelled"),
    )
    if cloisonne:
        pay_stmt = pay_stmt.where(Payment.received_by == received_by)
    # Le meme predicat que la liste, pas une recopie. Sans lui, filtrer sur
    # « Annule » laissait le bandeau annoncer tout l'argent recu au-dessus
    # d'un tableau qui en montrait trois : deux chiffres, deux perimetres,
    # et rien a l'ecran pour dire lequel on lit.
    pay_stmt = await apply_payment_scope(db, pay_stmt, filtres)

    pay_row = (await db.execute(pay_stmt)).one()

    total_pending = float(pay_row.total_pending)
    total_cancelled = float(pay_row.total_cancelled)
    payment_count = pay_row.payment_count
    if total_expected is not None:
        completion_rate = round(total_paid / total_expected * 100, 1) if total_expected > 0 else 0.0

    return PaymentSummaryResponse(
        total_expected=total_expected,
        total_paid=total_paid,
        total_pending=total_pending,
        total_cancelled=total_cancelled,
        payment_count=payment_count,
        completion_rate=completion_rate,
    )
