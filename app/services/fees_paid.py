"""Combien a réellement été versé sur chaque frais — une seule vérité.

`EnrollmentFee.payments` s'appuie sur `Payment.enrollment_fee_id`, **déprécié
depuis la migration 0028**. Le chemin d'écriture a migré vers
`PaymentAllocation`, le chemin de lecture non. Tout code qui somme encore la
vieille relation sous-estime donc ce qu'une famille a payé — et, sur les
portails, c'est la famille elle-même qui lit ce chiffre faux.

Le calcul vit ici, à un seul endroit, parce qu'un montant dû ne peut pas
valoir trois sommes différentes selon l'écran qui l'affiche.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


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
