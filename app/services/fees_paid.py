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


def _par_frais(rows: object) -> dict[int, Decimal]:
    """Indexe une somme groupée par frais, en `Decimal`.

    En `Decimal` et pas en `float` : ce sont des francs CFA, et le reste du
    calcul — `EnrollmentFee.amount`, `PaymentAllocation.amount` — est en
    `Decimal`. Rendre des flottants obligeait chaque appelant à recharger le
    montant par `Decimal(str(...))` avant de le soustraire, un aller-retour
    qui n'existait que pour réparer le type qu'on venait de perdre.
    """
    return {int(fee_id): Decimal(str(total or 0)) for fee_id, total in rows.all()}  # type: ignore[attr-defined]


def _verse_par_frais(*conditions: object):
    """Le socle commun : les allocations encaissées, groupées par frais.

    Trois lectures s'en servent — un élève, une inscription, une classe. Ce
    qu'elles partagent vraiment, et qui ne doit exister qu'une fois, c'est le
    filtre `completed` : la réversibilité d'une annulation ne tient que parce
    que tout total joint `Payment` et écarte ce qui n'est pas encaissé, et il
    suffirait d'une requête écrite sans ce filtre pour ressusciter de l'argent
    rendu. `tests/services/test_payment_cancel_reversal.py` existe pour ça.

    **La jointure sur l'inscription n'est pas ici**, et c'est délibéré. Lire
    les versements d'une inscription se fait par `EnrollmentFee.enrollment_id`,
    sans jamais toucher la table des inscriptions ; la poser pour tout le monde
    donnerait à cette lecture une dépendance qu'elle n'a pas. Les deux lectures
    qui ont besoin de l'inscription l'ajoutent elles-mêmes, en une ligne
    visible.
    """
    from app.models.fee import EnrollmentFee, Payment, PaymentAllocation, PaymentStatus

    return (
        select(
            PaymentAllocation.enrollment_fee_id,
            func.coalesce(func.sum(PaymentAllocation.amount), 0),
        )
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .where(Payment.status == PaymentStatus.COMPLETED.value, *conditions)
        .group_by(PaymentAllocation.enrollment_fee_id)
    )


async def paid_by_enrollment_fee(db: AsyncSession, student_id: int) -> dict[int, Decimal]:
    """Montant encaissé sur chaque frais de l'élève, indexé par frais.

    Une seule requête groupée : sommer en Python sur des relations chargées
    coûterait une requête par frais.
    """
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee

    stmt = (
        _verse_par_frais()
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .where(Enrollment.student_id == student_id)
    )
    return _par_frais(await db.execute(stmt))


async def paid_by_enrollment(db: AsyncSession, enrollment_id: int) -> dict[int, Decimal]:
    """Même calcul, borné à une inscription plutôt qu'à un élève.

    Utile aux portails, qui affichent une année à la fois : un élève qui a
    redoublé a deux inscriptions, et mélanger leurs versements ferait
    apparaître comme soldée une année qui ne l'est pas.
    """
    from app.models.fee import EnrollmentFee

    return _par_frais(
        await db.execute(_verse_par_frais(EnrollmentFee.enrollment_id == enrollment_id))
    )


async def paid_by_class(
    db: AsyncSession, *, class_id: int, academic_year_id: int
) -> dict[int, Decimal]:
    """Même calcul, pour toute une classe d'un coup.

    La lecture par classe existe parce qu'on la regarde par classe : savoir
    qui a soldé sa scolarité et qui n'a pas remis sa tenue se demande sur
    quarante élèves à la fois. Appeler `paid_by_enrollment` en boucle
    coûterait une requête par élève sur un écran qui les montre tous.
    """
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee

    stmt = (
        _verse_par_frais()
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .where(
            Enrollment.class_id == class_id,
            Enrollment.academic_year_id == academic_year_id,
        )
    )
    return _par_frais(await db.execute(stmt))


def _allocations_sur_frais_dus():
    """Le socle du calcul : les allocations posées sur ce qui reste dû.

    Frais obligatoires, non exonérés, versements encaissés. Un seul endroit
    décrit ce périmètre, parce qu'un chiffre calculé sur deux périmètres
    différents finit toujours par en contredire un autre à l'écran.
    """
    from app.models.fee import (
        NOT_CASH_DUE,
        EnrollmentFee,
        FeeCategory,
        FeeVariant,
        Payment,
        PaymentAllocation,
        PaymentStatus,
    )

    return (
        select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .join(EnrollmentFee, EnrollmentFee.id == PaymentAllocation.enrollment_fee_id)
        .join(FeeVariant, FeeVariant.id == EnrollmentFee.fee_variant_id)
        .join(FeeCategory, FeeCategory.id == FeeVariant.fee_category_id)
        .where(
            Payment.status == PaymentStatus.COMPLETED.value,
            FeeCategory.is_mandatory.is_(True),
            EnrollmentFee.status.notin_(NOT_CASH_DUE),
        )
    )


async def paid_on_mandatory(db: AsyncSession, enrollment_id: int) -> Decimal:
    """Ce qu'une famille a versé sur les frais obligatoires encore dus.

    Le pendant exact de `installment_repository.mandatory_total`, qui dit ce
    qui est attendu : même périmètre de frais des deux côtés, sans quoi la
    soustraction ne veut rien dire.

    Sommer `Payment.amount` — le versement dans son entier — donnait ce
    résultat-là : une famille verse 25 000 sur l'Inscription, l'école lui
    accorde ensuite une bourse et exonère l'Inscription. Le montant attendu
    baisse de 25 000, le montant versé ne bouge pas, et la famille apparaît
    en avance de 25 000 sur une scolarité qu'elle n'a jamais payée.
    L'échéancier cesse alors de la signaler en retard — or c'est lui qui
    commande la retenue des documents administratifs.

    On somme donc les **allocations** posées sur les frais obligatoires non
    exonérés : l'argent imputé à un frais qui n'est plus dû sort du calcul
    en même temps que le frais.
    """
    from app.models.fee import EnrollmentFee

    stmt = _allocations_sur_frais_dus().where(EnrollmentFee.enrollment_id == enrollment_id)
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))


async def paid_on_mandatory_for_year(
    db: AsyncSession, academic_year_id: int | None = None
) -> Decimal:
    """Le même calcul, pour toute une année scolaire.

    C'est le chiffre du tableau de bord. Il se lisait auparavant comme la
    somme brute des versements encaissés, face à un attendu qui totalisait
    tous les frais, exonérés et facultatifs compris : une famille exonérée
    après avoir versé restait comptée comme ayant payé, et le taux d'avancement
    de l'école divergeait de la fiche de chacun de ses élèves.
    """
    from app.models.enrollment import Enrollment
    from app.models.fee import EnrollmentFee

    stmt = _allocations_sur_frais_dus()
    if academic_year_id is not None:
        stmt = stmt.join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id).where(
            Enrollment.academic_year_id == academic_year_id
        )
    return Decimal(str((await db.execute(stmt)).scalar_one() or 0))


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
