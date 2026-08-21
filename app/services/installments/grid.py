"""Écriture de la grille de tranches et des accords négociés."""

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.installment import FeeInstallmentKind
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
            kind=r.kind,
            percentage=float(r.percentage) if r.percentage is not None else None,
            amount=float(r.amount) if r.amount is not None else None,
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
    """Remplace la grille d'une année.

    Deux écritures cohabitent, et la validation suit cette division :

    - **Les pourcentages, s'il y en a, doivent totaliser exactement 100 %.**
      Ils se partagent le reste après montants fermes ; en laisser une part
      dehors reviendrait à ne planifier qu'une partie de la scolarité.
    - **Les montants fermes ne sont pas contraints en somme.** On ne peut pas
      les comparer au total dû ici : ce total n'existe pas au niveau d'une
      année, il change avec le niveau, la série et l'affectation de chaque
      élève. Refuser une grille sur la base d'un total inventé bloquerait des
      écoles pour un chiffre faux ; le garde-fou vit donc là où l'assiette est
      connue, à la résolution de l'échéancier, où un montant ferme ne peut
      jamais réclamer plus que l'élève ne doit. L'écran, lui, annonce la somme
      des montants fermes et la simule sur un niveau représentatif, pour que
      la directrice voie ses chiffres avant d'enregistrer.

    Une grille faite uniquement de montants fermes est donc légitime : c'est le
    cas d'une école qui affiche un échéancier identique pour tous ses élèves.
    """
    percentages = [
        Decimal(str(i.percentage))
        for i in data.installments
        if i.kind is FeeInstallmentKind.PERCENTAGE and i.percentage is not None
    ]
    if percentages and not is_complete_grid(percentages):
        total = percentages_sum(percentages)
        raise HTTPException(
            status_code=422,
            detail=(
                f"Les tranches en pourcentage totalisent {total} % au lieu de 100 %. "
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
                    "kind": i.kind.value,
                    "percentage": i.percentage,
                    "amount": i.amount,
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


async def _assert_enrollment_exists(db: AsyncSession, enrollment_id: int) -> None:
    """Refuse tot sur une inscription inconnue.

    Sans ce controle, `mandatory_total` renvoie 0 pour un identifiant qui
    n'existe pas, et l'utilisateur recoit « l'echeancier totalise 150 000 FCFA
    alors que les frais s'elevent a 0 FCFA » : il cherche une erreur de
    montants alors que l'inscription n'existe simplement plus.
    """
    from app.models.enrollment import Enrollment

    exists = (
        await db.execute(select(Enrollment.id).where(Enrollment.id == enrollment_id))
    ).scalar_one_or_none()
    if exists is None:
        raise NotFoundError("Enrollment", enrollment_id)


async def set_enrollment_plan(
    db: AsyncSession, enrollment_id: int, data: EnrollmentPlanUpdate, *, updated_by: int
) -> None:
    """Fixe l'échéancier négocié d'une famille.

    Le total doit correspondre exactement aux frais obligatoires : un accord
    qui couvre moins que le dû ferait croire la famille quitte alors qu'elle
    reste redevable, et un accord qui couvre plus lui réclamerait de l'argent
    qu'elle ne doit pas.
    """
    await _assert_enrollment_exists(db, enrollment_id)
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
    """Supprime l'accord : la famille repasse sur la grille de l'établissement.

    Ne journalise que si un accord existait vraiment. Ecrire « accord
    supprime » quand il n'y avait rien a supprimer remplit le journal de
    faits qui ne se sont pas produits, et c'est precisement ce qu'un journal
    d'audit ne doit jamais faire.
    """
    await _assert_enrollment_exists(db, enrollment_id)

    async with db.begin_nested():
        removed = await repo.clear_enrollment_plan(db, enrollment_id)
        if removed:
            await audit_log(
                db,
                entity_type="enrollment_installment_plan",
                action=AuditAction.DELETE,
                user_id=updated_by,
                entity_id=enrollment_id,
            )
    await db.commit()
