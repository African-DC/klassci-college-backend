"""Accès données des tranches — grille d'année, échéancier négocié, totaux."""

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentStatus,
)
from app.models.installment import EnrollmentInstallment, FeeInstallment


async def list_year_grid(db: AsyncSession, academic_year_id: int) -> list[FeeInstallment]:
    stmt = (
        select(FeeInstallment)
        .where(FeeInstallment.academic_year_id == academic_year_id)
        .order_by(FeeInstallment.position)
    )
    return list((await db.execute(stmt)).scalars().all())


async def replace_year_grid(
    db: AsyncSession, academic_year_id: int, rows: list[dict[str, object]]
) -> list[FeeInstallment]:
    """Remplace la grille d'une année en une fois.

    Remplacement complet plutôt que création/modification/suppression ligne à
    ligne : la somme doit faire 100 %, donc une grille n'est valide que prise
    entièrement. Éditer une tranche isolément laisserait forcément la grille
    invalide entre deux appels.
    """
    await db.execute(
        delete(FeeInstallment).where(FeeInstallment.academic_year_id == academic_year_id)
    )
    created = [
        FeeInstallment(
            academic_year_id=academic_year_id,
            name=str(row["name"]),
            position=int(row["position"]),  # type: ignore[call-overload]
            percentage=Decimal(str(row["percentage"])),
            due_date=row["due_date"],  # type: ignore[arg-type]
        )
        for row in rows
    ]
    db.add_all(created)
    await db.flush()
    return created


async def list_enrollment_plan(db: AsyncSession, enrollment_id: int) -> list[EnrollmentInstallment]:
    stmt = (
        select(EnrollmentInstallment)
        .where(EnrollmentInstallment.enrollment_id == enrollment_id)
        .order_by(EnrollmentInstallment.position)
    )
    return list((await db.execute(stmt)).scalars().all())


async def replace_enrollment_plan(
    db: AsyncSession, enrollment_id: int, rows: list[dict[str, object]]
) -> list[EnrollmentInstallment]:
    await db.execute(
        delete(EnrollmentInstallment).where(EnrollmentInstallment.enrollment_id == enrollment_id)
    )
    created = [
        EnrollmentInstallment(
            enrollment_id=enrollment_id,
            name=str(row["name"]),
            position=int(row["position"]),  # type: ignore[call-overload]
            amount=Decimal(str(row["amount"])),
            due_date=row["due_date"],  # type: ignore[arg-type]
        )
        for row in rows
    ]
    db.add_all(created)
    await db.flush()
    return created


async def clear_enrollment_plan(db: AsyncSession, enrollment_id: int) -> None:
    await db.execute(
        delete(EnrollmentInstallment).where(EnrollmentInstallment.enrollment_id == enrollment_id)
    )


async def mandatory_total(db: AsyncSession, enrollment_id: int) -> Decimal:
    """Total des frais OBLIGATOIRES d'une inscription.

    Les frais optionnels (tenue, cantine, transport) sont exclus : ils ne sont
    pas dus par tout le monde, les inclure dans l'échéancier ferait apparaître
    en retard une famille qui n'a simplement pas souscrit à la cantine.

    Les frais exonérés sont exclus aussi : ils ne sont plus dus.
    """
    stmt = (
        select(func.coalesce(func.sum(EnrollmentFee.amount), 0))
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .join(FeeCategory, FeeCategory.id == FeeVariant.fee_category_id)
        .where(
            EnrollmentFee.enrollment_id == enrollment_id,
            FeeCategory.is_mandatory.is_(True),
            EnrollmentFee.status != EnrollmentFeeStatus.WAIVED,
        )
    )
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))


async def total_paid(db: AsyncSession, enrollment_id: int) -> Decimal:
    """Total réellement encaissé sur l'inscription.

    Seuls les versements `completed` comptent : un versement annulé ou
    remboursé ne doit pas éteindre une échéance.
    """
    stmt = select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.enrollment_id == enrollment_id,
        Payment.status == PaymentStatus.COMPLETED.value,
    )
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))
