"""Lectures dédiées au journal des versements : export intégral et encaisseurs.

Séparé de `payment_repository` pour deux raisons. La première est de taille :
le repository des versements couvre déjà l'écriture, les allocations et les
frais. La seconde tient au métier : un export n'est pas une page. Il ne
pagine pas, il s'ordonne dans le sens de lecture d'un journal comptable (du
plus ancien au plus récent) et il est borné, parce qu'un classeur de 40 000
lignes n'est pas un document, c'est une panne.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.fee import EnrollmentFee, FeeVariant, Payment, PaymentAllocation
from app.models.user import User
from app.repositories.payment_filters import PaymentFilters, apply_payment_scope

# Au-delà, le document cesse de rendre service : personne ne relit trente
# mille lignes, et la génération se met à peser sur le serveur pendant les
# heures de guichet. L'utilisateur est invité à resserrer sa période.
JOURNAL_MAX_ROWS = 5000


def _journal_options():
    """Les relations que la ligne de journal lit — chargées, jamais paresseuses.

    Sans ce chargement explicite, chaque ligne déclencherait une requête au
    moment du rendu, hors contexte async : c'est le `MissingGreenlet` qui
    transforme un export en 500 en texte brut.
    """
    return (
        selectinload(Payment.enrollment).selectinload(Enrollment.student),
        selectinload(Payment.allocations)
        .selectinload(PaymentAllocation.enrollment_fee)
        .selectinload(EnrollmentFee.fee_variant)
        .selectinload(FeeVariant.category),
        selectinload(Payment.received_by_user).selectinload(User.staff_profile),
        selectinload(Payment.received_by_user).selectinload(User.teacher_profile),
        selectinload(Payment.received_by_user).selectinload(User.student_profile),
        selectinload(Payment.received_by_user).selectinload(User.parent_profile),
    )


async def count_for_journal(db: AsyncSession, filters: PaymentFilters) -> int:
    """Nombre de versements que l'export retiendrait, avant de le produire."""
    base = await apply_payment_scope(db, select(Payment.id), filters)
    stmt = select(func.count()).select_from(base.subquery())
    return int((await db.execute(stmt)).scalar() or 0)


async def list_for_journal(db: AsyncSession, filters: PaymentFilters) -> list[Payment]:
    """Tous les versements retenus, du plus ancien au plus récent.

    L'ordre chronologique est celui du journal de caisse : on relit une
    journée dans le sens où elle s'est déroulée, pas en commençant par la fin.
    """
    stmt = (
        await apply_payment_scope(db, select(Payment).options(*_journal_options()), filters)
    ).order_by(Payment.created_at.asc(), Payment.id.asc()).limit(JOURNAL_MAX_ROWS)
    return list((await db.execute(stmt)).scalars().all())


async def get_cashier(db: AsyncSession, user_id: int) -> User | None:
    """Le compte encaisseur, chargé de quoi être nommé dans un en-tête."""
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
            selectinload(User.parent_profile),
        )
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_cashiers(db: AsyncSession) -> list[User]:
    """Les comptes ayant réellement encaissé au moins un versement.

    On part des versements et non de la liste des comptes : proposer dans un
    filtre une personne qui n'a jamais tenu la caisse ne mène qu'à un tableau
    vide, et la vraie question — « qui a encaissé cet argent ? » — se pose
    toujours au passé.
    """
    encaisseurs = select(Payment.received_by).where(Payment.received_by.is_not(None)).distinct()
    stmt = (
        select(User)
        .where(User.id.in_(encaisseurs))
        .options(
            selectinload(User.staff_profile),
            selectinload(User.teacher_profile),
            selectinload(User.student_profile),
            selectinload(User.parent_profile),
        )
        .order_by(User.email.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "JOURNAL_MAX_ROWS",
    "count_for_journal",
    "get_cashier",
    "list_cashiers",
    "list_for_journal",
]
