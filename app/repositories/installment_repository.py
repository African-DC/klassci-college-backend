"""Accès données des tranches — grille d'année, échéancier négocié, totaux."""

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, FeeCategory, FeeVariant
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
            kind=str(row["kind"]),
            # L'écriture non retenue reste vide : une tranche en francs qui
            # garderait un pourcentage résiduel laisserait deux vérités dans
            # la même ligne, et l'écran finirait par afficher la mauvaise.
            percentage=(
                Decimal(str(row["percentage"])) if row.get("percentage") is not None else None
            ),
            amount=(Decimal(str(row["amount"])) if row.get("amount") is not None else None),
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


async def clear_enrollment_plan(db: AsyncSession, enrollment_id: int) -> int:
    """Retire l'accord negocie et renvoie le nombre d'echeances supprimees.

    Le compte permet a l'appelant de ne journaliser que ce qui s'est
    reellement produit.
    """
    result = await db.execute(
        delete(EnrollmentInstallment).where(EnrollmentInstallment.enrollment_id == enrollment_id)
    )
    return int(result.rowcount or 0)


async def mandatory_total(db: AsyncSession, enrollment_id: int) -> Decimal:
    """Total des frais OBLIGATOIRES d'une inscription.

    Les frais optionnels (tenue, cantine, transport) sont exclus : ils ne sont
    pas dus par tout le monde, les inclure dans l'échéancier ferait apparaître
    en retard une famille qui n'a simplement pas souscrit à la cantine.

    Les frais exonérés sont exclus aussi : ils ne sont plus dus.
    """
    stmt = _frais_dus().where(EnrollmentFee.enrollment_id == enrollment_id)
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))


def _frais_dus():
    """Le socle du calcul : ce qui reste dû, obligatoire et non exonéré."""
    return (
        select(func.coalesce(func.sum(EnrollmentFee.amount), 0))
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .join(FeeCategory, FeeCategory.id == FeeVariant.fee_category_id)
        .where(
            FeeCategory.is_mandatory.is_(True),
            EnrollmentFee.status != EnrollmentFeeStatus.WAIVED,
        )
    )


async def mandatory_total_for_year(
    db: AsyncSession, academic_year_id: int | None = None
) -> Decimal:
    """Le même total, pour toute une année scolaire.

    Le pendant exact de `fees_paid.paid_on_mandatory_for_year`. Le tableau de
    bord totalisait auparavant TOUS les frais d'élèves — facultatifs et
    exonérés compris — face à un encaissé qui, lui, ne comptait que des
    versements : les deux moitiés du taux d'avancement ne parlaient pas de la
    même dette.
    """
    from app.models.enrollment import Enrollment

    stmt = _frais_dus()
    if academic_year_id is not None:
        stmt = stmt.join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id).where(
            Enrollment.academic_year_id == academic_year_id
        )
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))
