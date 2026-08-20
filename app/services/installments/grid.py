"""Écriture de la grille de tranches et des accords négociés."""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.repositories import installment_repository as repo
from app.schemas.installment import (
    EnrollmentPlanUpdate,
    FeeInstallmentGridUpdate,
    FeeInstallmentResponse,
)
from app.services.installments._math import is_complete_grid, percentages_sum


def _ensure_distinct_positions(positions: list[int], label: str) -> None:
    if len(positions) != len(set(positions)):
        raise HTTPException(
            status_code=422,
            detail=f"Deux {label} portent le même rang. Chaque rang doit être unique.",
        )


async def list_grid(db: AsyncSession, academic_year_id: int) -> list[FeeInstallmentResponse]:
    rows = await repo.list_year_grid(db, academic_year_id)
    return [
        FeeInstallmentResponse(
            id=r.id,
            academic_year_id=r.academic_year_id,
            name=r.name,
            position=r.position,
            percentage=float(r.percentage),
            due_date=r.due_date,
        )
        for r in rows
    ]


async def replace_grid(
    db: AsyncSession,
    academic_year_id: int,
    data: FeeInstallmentGridUpdate,
    *,
    updated_by: int,
) -> list[FeeInstallmentResponse]:
    """Remplace la grille d'une année. La somme doit faire exactement 100 %."""
    percentages = [Decimal(str(i.percentage)) for i in data.installments]
    if not is_complete_grid(percentages):
        total = percentages_sum(percentages)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Les tranches totalisent {total} % au lieu de 100 %. "
                "Une grille incomplète laisserait une part des frais sans échéance, "
                "et une grille excédentaire réclamerait plus que le montant dû."
            ),
        )
    _ensure_distinct_positions([i.position for i in data.installments], "tranches")

    async with db.begin_nested():
        await repo.replace_year_grid(
            db,
            academic_year_id,
            [
                {
                    "name": i.name,
                    "position": i.position,
                    "percentage": i.percentage,
                    "due_date": i.due_date,
                }
                for i in data.installments
            ],
        )
        await audit_log(
            db,
            entity_type="fee_installment_grid",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=academic_year_id,
            new_values={
                "academic_year_id": academic_year_id,
                "installments": [i.model_dump(mode="json") for i in data.installments],
            },
        )
    await db.commit()
    return await list_grid(db, academic_year_id)


async def set_enrollment_plan(
    db: AsyncSession, enrollment_id: int, data: EnrollmentPlanUpdate, *, updated_by: int
) -> None:
    """Fixe l'échéancier négocié d'une famille.

    Le total doit correspondre exactement aux frais obligatoires : un accord
    qui couvre moins que le dû ferait croire la famille quitte alors qu'elle
    reste redevable, et un accord qui couvre plus lui réclamerait de l'argent
    qu'elle ne doit pas.
    """
    total_mandatory = await repo.mandatory_total(db, enrollment_id)
    planned = sum((Decimal(str(i.amount)) for i in data.installments), Decimal("0"))
    if planned != total_mandatory:
        raise HTTPException(
            status_code=422,
            detail=(
                f"L'échéancier totalise {planned:.0f} FCFA alors que les frais obligatoires "
                f"s'élèvent à {total_mandatory:.0f} FCFA. Les deux doivent correspondre."
            ),
        )
    _ensure_distinct_positions([i.position for i in data.installments], "échéances")

    async with db.begin_nested():
        await repo.replace_enrollment_plan(
            db,
            enrollment_id,
            [
                {
                    "name": i.name,
                    "position": i.position,
                    "amount": i.amount,
                    "due_date": i.due_date,
                }
                for i in data.installments
            ],
        )
        await audit_log(
            db,
            entity_type="enrollment_installment_plan",
            action=AuditAction.UPDATE,
            user_id=updated_by,
            entity_id=enrollment_id,
            new_values={"installments": [i.model_dump(mode="json") for i in data.installments]},
        )
    await db.commit()


async def clear_enrollment_plan(db: AsyncSession, enrollment_id: int, *, updated_by: int) -> None:
    """Supprime l'accord : la famille repasse sur la grille de l'établissement."""
    async with db.begin_nested():
        await repo.clear_enrollment_plan(db, enrollment_id)
        await audit_log(
            db,
            entity_type="enrollment_installment_plan",
            action=AuditAction.DELETE,
            user_id=updated_by,
            entity_id=enrollment_id,
        )
    await db.commit()
