"""Repository paiements — accès DB pour Payment, PaymentAllocation, EnrollmentFee.

Architecture (refactor 2026-05-17) :
- La source de vérité du "montant payé sur un fee" est `payment_allocations`
  (somme des splits sur les paiements completed). L'ancien chemin par
  `payments.enrollment_fee_id` reste pour les vieilles rows mais ne doit
  plus être écrit.
- Les nouveaux paiements passent par `record_enrollment_payment` qui crée
  Payment + N PaymentAllocation en transaction.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.fee import (
    EnrollmentFee,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentAllocation,
    PaymentStatus,
)

# ---------------------------------------------------------------------------
# Loaders communs (selectinload exhaustif — voir preload-relations-after-commit)
# ---------------------------------------------------------------------------


def _payment_full_options():
    """Tout ce que le service / le PDF / la notif consomment post-commit."""
    from app.models.user import Student

    return (
        # Pour le notif dispatch
        selectinload(Payment.enrollment)
        .selectinload(Enrollment.student)
        .selectinload(Student.user),
        # Pour les allocations enrichies dans la response
        selectinload(Payment.allocations)
        .selectinload(PaymentAllocation.enrollment_fee)
        .selectinload(EnrollmentFee.fee_variant)
        .selectinload(FeeVariant.category),
        # Pour l'ancien champ `fee_name` (rétrocompat response)
        selectinload(Payment.enrollment_fee)
        .selectinload(EnrollmentFee.fee_variant)
        .selectinload(FeeVariant.category),
    )


# ---------------------------------------------------------------------------
# Payment getters
# ---------------------------------------------------------------------------


async def get_payment_by_id(db: AsyncSession, payment_id: int) -> Payment | None:
    """Retourne un paiement par ID avec toutes les relations consommées.

    Inclut maintenant `allocations` (avec category) + `enrollment.student.user`.
    """
    stmt = select(Payment).where(Payment.id == payment_id).options(*_payment_full_options())
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_payment_with_allocations(db: AsyncSession, payment_id: int) -> Payment | None:
    """Alias explicite — même chargement que `get_payment_by_id`."""
    return await get_payment_by_id(db, payment_id)


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
) -> tuple[list[Payment], int]:
    """Retourne une page de paiements avec le total.

    `received_by` cloisonne un caissier sur sa propre caisse. Le filtre est
    appliqué ici, dans la requête, et non après coup sur la page : filtrer en
    Python laisserait le total et la pagination compter les versements des
    collègues, et le caissier verrait « 128 versements » en n'en lisant que
    les siens.
    """
    base = select(Payment).options(*_payment_full_options())

    if received_by is not None:
        base = base.where(Payment.received_by == received_by)

    if status is not None:
        base = base.where(Payment.status == status)
    if method is not None:
        base = base.where(Payment.method == method)
    if enrollment_id is not None:
        base = base.where(Payment.enrollment_id == enrollment_id)
    if enrollment_fee_id is not None:
        # Le filtre passe par les allocations (nouveau modèle)
        base = base.where(
            Payment.id.in_(
                select(PaymentAllocation.payment_id).where(
                    PaymentAllocation.enrollment_fee_id == enrollment_fee_id
                )
            )
        )
    if date_from is not None:
        base = base.where(Payment.created_at >= date_from)
    if date_to is not None:
        base = base.where(Payment.created_at <= date_to)

    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await db.execute(count_stmt)).scalar() or 0

    stmt = base.offset((page - 1) * size).limit(size).order_by(Payment.id.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows), total


async def get_payments_by_enrollment_id(db: AsyncSession, enrollment_id: int) -> list[Payment]:
    """Retourne tous les paiements d'une inscription (via Payment.enrollment_id)."""
    stmt = (
        select(Payment)
        .where(Payment.enrollment_id == enrollment_id)
        .options(*_payment_full_options())
        .order_by(Payment.id.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# EnrollmentFee getters
# ---------------------------------------------------------------------------


async def get_enrollment_fee_by_id(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee par ID."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_enrollment_fee_for_update(
    db: AsyncSession, enrollment_fee_id: int
) -> EnrollmentFee | None:
    """Retourne un EnrollmentFee avec verrou FOR UPDATE (race condition guard)."""
    stmt = select(EnrollmentFee).where(EnrollmentFee.id == enrollment_fee_id).with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_unpaid_fees_ordered_by_priority(
    db: AsyncSession, enrollment_id: int
) -> list[EnrollmentFee]:
    """Frais impayés d'une inscription triés par priorité catégorie ASC.

    Lower priority = paid first. Exclut les WAIVED et PAID. Inclut les
    PARTIAL (peuvent encore recevoir un complément). Verrouille les rows
    avec FOR UPDATE pour la transaction de paiement.
    """
    from app.models.fee import EnrollmentFeeStatus

    stmt = (
        select(EnrollmentFee)
        .join(FeeVariant, EnrollmentFee.fee_variant_id == FeeVariant.id)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .where(
            EnrollmentFee.enrollment_id == enrollment_id,
            EnrollmentFee.status.in_(
                [EnrollmentFeeStatus.PENDING.value, EnrollmentFeeStatus.PARTIAL.value]
            ),
        )
        .options(
            selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category),
        )
        .order_by(FeeCategory.priority.asc(), EnrollmentFee.id.asc())
        .with_for_update(of=EnrollmentFee)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_enrollment_fees_ordered_by_priority(
    db: AsyncSession, enrollment_id: int
) -> list[EnrollmentFee]:
    """Tous les frais d'une inscription triés par priorité (pour preview UI)."""
    stmt = (
        select(EnrollmentFee)
        .join(FeeVariant, EnrollmentFee.fee_variant_id == FeeVariant.id)
        .join(FeeCategory, FeeVariant.fee_category_id == FeeCategory.id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .options(
            selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category),
        )
        .order_by(FeeCategory.priority.asc(), EnrollmentFee.id.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Totals calculation — source of truth = payment_allocations
# ---------------------------------------------------------------------------


async def get_total_paid_for_enrollment_fee(db: AsyncSession, enrollment_fee_id: int) -> Decimal:
    """Total alloué à un fee depuis les paiements COMPLETED.

    Source de vérité = `payment_allocations`. Exclut les payments
    cancelled/failed/refunded.
    """
    stmt = (
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .join(Payment, PaymentAllocation.payment_id == Payment.id)
        .where(
            PaymentAllocation.enrollment_fee_id == enrollment_fee_id,
            Payment.status == PaymentStatus.COMPLETED.value,
        )
    )
    result = await db.execute(stmt)
    return Decimal(str(result.scalar()))


# ---------------------------------------------------------------------------
# Enrollment loader (avec FOR UPDATE pour la transaction de paiement)
# ---------------------------------------------------------------------------


async def get_enrollment_for_update(db: AsyncSession, enrollment_id: int) -> Enrollment | None:
    """Verrouille l'inscription le temps du calcul de l'allocation."""
    from app.models.user import Student

    stmt = (
        select(Enrollment)
        .where(Enrollment.id == enrollment_id)
        .options(
            selectinload(Enrollment.student).selectinload(Student.user),
        )
        .with_for_update(of=Enrollment)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Payment / Allocation writers
# ---------------------------------------------------------------------------


async def create_payment(
    db: AsyncSession,
    *,
    enrollment_id: int,
    amount: Decimal,
    method: str,
    status: str,
    reference: str | None,
    received_by: int | None,
    notes: str | None,
    enrollment_fee_id: int | None = None,
) -> Payment:
    """Crée un Payment (acte caissier) et le flush pour obtenir l'ID.

    `enrollment_fee_id` reste accepté pour le path legacy (rétrocompat
    POST /payments) — sinon NULL.
    """
    payment = Payment(
        enrollment_id=enrollment_id,
        enrollment_fee_id=enrollment_fee_id,
        amount=amount,
        method=method,
        status=status,
        reference=reference,
        received_by=received_by,
        notes=notes,
    )
    db.add(payment)
    await db.flush()
    return payment


async def create_allocation(
    db: AsyncSession,
    *,
    payment_id: int,
    enrollment_fee_id: int,
    amount: Decimal,
) -> PaymentAllocation:
    """Crée un split PaymentAllocation."""
    allocation = PaymentAllocation(
        payment_id=payment_id,
        enrollment_fee_id=enrollment_fee_id,
        amount=amount,
    )
    db.add(allocation)
    await db.flush()
    return allocation


async def get_allocations_for_payment(db: AsyncSession, payment_id: int) -> list[PaymentAllocation]:
    """Toutes les allocations d'un Payment, avec category pour l'audit."""
    stmt = (
        select(PaymentAllocation)
        .where(PaymentAllocation.payment_id == payment_id)
        .options(
            selectinload(PaymentAllocation.enrollment_fee)
            .selectinload(EnrollmentFee.fee_variant)
            .selectinload(FeeVariant.category),
        )
        .order_by(PaymentAllocation.id.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())
