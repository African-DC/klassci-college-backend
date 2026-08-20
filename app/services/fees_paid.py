"""Combien a réellement été versé sur chaque frais — une seule vérité.

`EnrollmentFee.payments` s'appuie sur `Payment.enrollment_fee_id`, **déprécié
depuis la migration 0028**. Le chemin d'écriture a migré vers
`PaymentAllocation`, le chemin de lecture non. Tout code qui somme encore la
vieille relation sous-estime donc ce qu'une famille a payé — et, sur les
portails, c'est la famille elle-même qui lit ce chiffre faux.

Le calcul vit ici, à un seul endroit, parce qu'un montant dû ne peut pas
valoir trois sommes différentes selon l'écran qui l'affiche.
"""

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.fee import Payment


async def paid_by_enrollment_fee(db: AsyncSession, student_id: int) -> dict[int, float]:
    """Montant encaissé sur chaque frais de l'élève, indexé par frais.

    Une seule requête groupée : sommer en Python sur des relations chargées
    coûterait une requête par frais.
    """
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee, Payment, PaymentAllocation, PaymentStatus

    stmt = (
        select(
            PaymentAllocation.enrollment_fee_id,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .where(
            Enrollment.student_id == student_id,
            Payment.status == PaymentStatus.COMPLETED.value,
        )
        .group_by(PaymentAllocation.enrollment_fee_id)
    )
    return {int(fee_id): float(total or 0) for fee_id, total in (await db.execute(stmt)).all()}


async def paid_by_enrollment(db: AsyncSession, enrollment_id: int) -> dict[int, float]:
    """Même calcul, borné à une inscription plutôt qu'à un élève.

    Utile aux portails, qui affichent une année à la fois : un élève qui a
    redoublé a deux inscriptions, et mélanger leurs versements ferait
    apparaître comme soldée une année qui ne l'est pas.
    """
    from app.models.fee import EnrollmentFee, Payment, PaymentAllocation, PaymentStatus

    stmt = (
        select(
            PaymentAllocation.enrollment_fee_id,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .where(
            EnrollmentFee.enrollment_id == enrollment_id,
            Payment.status == PaymentStatus.COMPLETED.value,
        )
        .group_by(PaymentAllocation.enrollment_fee_id)
    )
    return {int(fee_id): float(total or 0) for fee_id, total in (await db.execute(stmt)).all()}


async def payments_by_enrollment_fee(
    db: AsyncSession, enrollment_id: int
) -> dict[int, list[tuple["Payment", Decimal]]]:
    """Versements imputés sur chaque frais, avec la part qui revient au frais.

    Le détail affiché sous un frais, pas seulement son total. Les portails le
    construisaient depuis `EnrollmentFee.payments` : depuis la migration 0028
    cette liste est vide, si bien que la famille voyait un frais soldé sans
    aucun versement en dessous, et pouvait croire l'argent perdu.

    Le montant renvoyé est celui de l'**allocation**, pas celui du versement :
    un versement de 50 000 réparti sur trois trimestres doit apparaître pour
    20 000 sous le premier, sinon la liste ne se recoupe plus avec le total.

    Aucun filtre sur le statut : un versement en attente ou annulé a sa place
    dans un historique, et l'appelant affiche déjà ce statut.
    """
    from app.models.fee import EnrollmentFee, Payment, PaymentAllocation

    stmt = (
        select(PaymentAllocation.enrollment_fee_id, Payment, PaymentAllocation.amount)
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .order_by(Payment.created_at, Payment.id)
    )

    par_frais: dict[int, list[tuple[Payment, Decimal]]] = {}
    for fee_id, payment, montant in (await db.execute(stmt)).all():
        par_frais.setdefault(int(fee_id), []).append((payment, montant))
    return par_frais


async def fee_ids_with_allocations(db: AsyncSession, enrollment_id: int) -> set[int]:
    """Frais de l'inscription sur lesquels de l'argent est déjà imputé.

    Distinct de `paid_by_enrollment`, et volontairement : ici on ne filtre
    **pas** sur `PaymentStatus.COMPLETED`. La question n'est pas « combien la
    famille a-t-elle versé » mais « ce frais porte-t-il une écriture ». Un
    versement encore en attente a déjà sa ligne d'allocation ; détruire le
    frais sous cette ligne violerait la clé étrangère `RESTRICT` et, surtout,
    ferait perdre sa contrepartie à un encaissement que la caisse a déjà
    enregistré.
    """
    from app.models.fee import EnrollmentFee, PaymentAllocation

    stmt = (
        select(PaymentAllocation.enrollment_fee_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .distinct()
    )
    return {int(fee_id) for fee_id in (await db.execute(stmt)).scalars().all()}
