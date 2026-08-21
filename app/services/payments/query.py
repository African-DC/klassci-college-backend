"""Read-only queries paiements : list, get, get_by_enrollment, summary."""

from datetime import datetime, time, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment
from app.models.fee import Payment, PaymentStatus
from app.repositories import installment_repository
from app.repositories import payment_repository as repo
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
    status: str | None = None,
    method: str | None = None,
    enrollment_fee_id: int | None = None,
    enrollment_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    received_by: int | None = None,
    page: int = 1,
    size: int = 20,
) -> PaymentListResponse:
    """Retourne une page de paiements.

    `received_by` est passé par le routeur quand l'appelant n'a pas
    `payments:read:all` : un caissier ne lit que sa propre caisse.
    """
    payments, total = await repo.list_payments(
        db,
        status=status,
        method=method,
        enrollment_fee_id=enrollment_fee_id,
        enrollment_id=enrollment_id,
        date_from=date_from,
        date_to=date_to,
        received_by=received_by,
        page=page,
        size=size,
    )
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


async def _belongs_to_year(db: AsyncSession, academic_year_id: int):
    """Condition « ce versement relève de cette année scolaire ».

    Une jointure interne sur l'inscription ferait disparaître des totaux tout
    versement dont l'élève a été supprimé : le tableau de bord annoncerait
    moins d'argent encaissé que le bordereau de caisse du même jour, et
    personne ne saurait lequel croire.

    On rattache donc le versement orphelin par sa date. C'est exact : une
    somme encaissée le 12 novembre relève de l'année scolaire qui couvre le
    12 novembre, que la fiche élève existe encore ou non.
    """
    dates = (
        await db.execute(
            select(AcademicYear.start_date, AcademicYear.end_date).where(
                AcademicYear.id == academic_year_id
            )
        )
    ).one_or_none()

    par_inscription = Enrollment.academic_year_id == academic_year_id
    if dates is None:
        return par_inscription

    start = datetime.combine(dates.start_date, time.min)
    # Borne haute exclusive au lendemain de la fin : un versement encaissé à
    # 16 h le dernier jour ne doit pas tomber hors de l'année.
    end = datetime.combine(dates.end_date, time.min) + timedelta(days=1)
    return or_(
        par_inscription,
        and_(
            Payment.enrollment_id.is_(None), Payment.created_at >= start, Payment.created_at < end
        ),
    )


async def get_payments_summary(
    db: AsyncSession,
    *,
    academic_year_id: int | None = None,
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
    """
    total_expected = float(
        await installment_repository.mandatory_total_for_year(db, academic_year_id)
    )
    total_paid = float(await fees_paid.paid_on_mandatory_for_year(db, academic_year_id))

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
    if academic_year_id is not None:
        pay_stmt = pay_stmt.select_from(Payment).outerjoin(
            Enrollment, Payment.enrollment_id == Enrollment.id
        )
        pay_stmt = pay_stmt.where(await _belongs_to_year(db, academic_year_id))

    pay_row = (await db.execute(pay_stmt)).one()

    total_pending = float(pay_row.total_pending)
    total_cancelled = float(pay_row.total_cancelled)
    payment_count = pay_row.payment_count
    completion_rate = round(total_paid / total_expected * 100, 1) if total_expected > 0 else 0.0

    return PaymentSummaryResponse(
        total_expected=total_expected,
        total_paid=total_paid,
        total_pending=total_pending,
        total_cancelled=total_cancelled,
        payment_count=payment_count,
        completion_rate=completion_rate,
    )
