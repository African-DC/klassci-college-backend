"""Répercuter un tarif modifié sur les inscriptions qui le portent déjà.

Changer le montant d'un tarif ne touchait pas les élèves déjà inscrits. Leur
dette gardait l'ancien montant, sans que rien ne le dise : une école qui
corrigeait une erreur de saisie voyait sa grille afficher 45 000 et ses
familles continuer de devoir 54 000.

Ce module fait le geste manquant, et rien de plus. Il ne régénère pas la
grille d'une inscription : il met à jour **les lignes qui portent ce
tarif-là**, pour l'année de ce tarif. Régénérer toute la grille parce qu'on a
ajusté le prix de la tenue reviendrait à rejouer six décisions pour en
corriger une.

La règle d'or du projet tient : **on ne touche jamais une ligne de frais sur
laquelle de l'argent est imputé.** Ici on ne détruit rien, on réécrit un
montant, mais réécrire le montant d'une ligne déjà payée ferait mentir le
reçu que la famille a en main, et pourrait rendre le reste dû négatif. Ces
lignes sont donc conservées telles quelles, et l'aperçu le dit avant que
l'école ne confirme.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    PaymentAllocation,
    is_not_cash_due,
)
from app.schemas.fee import FeePropagationPreview, FeePropagationResult
from app.services.deletion import Dependent

#: Une inscription refusée ou annulée ne doit plus rien : sa dette est close,
#: la relancer à la hausse ferait réapparaître un impayé sur un dossier clos.
_STATUTS_HORS_JEU = (EnrollmentStatus.REJETE, EnrollmentStatus.ANNULE)


@dataclass(frozen=True, slots=True)
class _Repartition:
    """Les lignes concernées, rangées par ce qui va leur arriver.

    Les quatre paquets forment une partition : leur somme est le nombre
    d'inscriptions concernées. Sans cela l'aperçu afficherait un total que
    son propre détail contredit, et c'est le genre d'écart qui fait douter
    de tout le reste de l'écran.
    """

    a_mettre_a_jour: tuple[EnrollmentFee, ...]
    deja_a_jour: int
    conservees_car_payees: int
    exonerees: int
    ecart_de_dette: Decimal

    @property
    def concernees(self) -> int:
        return (
            len(self.a_mettre_a_jour)
            + self.deja_a_jour
            + self.conservees_car_payees
            + self.exonerees
        )


async def _load_variant(db: AsyncSession, variant_id: int) -> FeeVariant:
    variant = (
        await db.execute(select(FeeVariant).where(FeeVariant.id == variant_id))
    ).scalar_one_or_none()
    if variant is None:
        raise NotFoundError("FeeVariant", variant_id)
    return variant


async def _category_name(db: AsyncSession, category_id: int) -> str:
    """Le nom lisible de la catégorie, ou son identifiant à défaut.

    Lu par une requête et non par `variant.category` : l'appelant a pu
    commiter entre-temps, et une relation non préchargée lève alors une
    erreur illisible au lieu de rendre un nom.
    """
    nom = (
        await db.execute(select(FeeCategory.name).where(FeeCategory.id == category_id))
    ).scalar_one_or_none()
    return nom or str(category_id)


async def _fee_ids_with_allocations(db: AsyncSession, fee_ids: list[int]) -> set[int]:
    """Parmi ces frais, ceux qui portent déjà une écriture de versement.

    Aucun filtre sur le statut du versement, pour la même raison que dans
    `fees_paid.fee_ids_with_allocations` : la question n'est pas « combien la
    famille a-t-elle payé » mais « cette ligne porte-t-elle une écriture ».
    Une seule requête pour tout le lot, là où interroger frais par frais
    coûterait une requête par élève de l'école.
    """
    if not fee_ids:
        return set()

    stmt = (
        select(PaymentAllocation.enrollment_fee_id)
        .where(PaymentAllocation.enrollment_fee_id.in_(fee_ids))
        .distinct()
    )
    return {int(fee_id) for fee_id in (await db.execute(stmt)).scalars().all()}


async def _repartir(db: AsyncSession, variant: FeeVariant) -> _Repartition:
    """Classe les lignes portant ce tarif selon ce qu'il faut leur faire.

    Le périmètre est volontairement étroit : les lignes rattachées à CE
    tarif, sur des inscriptions vivantes de l'année de CE tarif. Une
    inscription d'une autre année garde son montant, parce que sa facture a
    été émise sous une autre grille.

    Les inscriptions archivées sont écartées sans qu'on l'écrive ici :
    `app.core.archive_filter` pose la règle une fois pour toutes les sessions.
    La répéter donnerait l'illusion que ce module la porte, et un test qui la
    vérifie ici passerait même si on la retirait.
    """
    stmt = (
        select(EnrollmentFee)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .where(
            EnrollmentFee.fee_variant_id == variant.id,
            Enrollment.academic_year_id == variant.academic_year_id,
            Enrollment.status.not_in(_STATUTS_HORS_JEU),
        )
        .order_by(EnrollmentFee.id)
    )
    lignes = list((await db.execute(stmt)).scalars().all())

    nouveau_montant = Decimal(str(variant.amount))
    exonerees = [f for f in lignes if f.status == EnrollmentFeeStatus.WAIVED]
    # Un dépôt en nature n'est pas une exonération DRENA : on l'ignore ici,
    # il ne gonfle ni fees_waived ni la dette à répercuter.
    dues = [f for f in lignes if not is_not_cash_due(f.status)]
    deja_a_jour = [f for f in dues if Decimal(str(f.amount)) == nouveau_montant]

    a_examiner = [f for f in dues if Decimal(str(f.amount)) != nouveau_montant]
    payees = await _fee_ids_with_allocations(db, [f.id for f in a_examiner])
    conservees = [f for f in a_examiner if f.id in payees]
    a_mettre_a_jour = [f for f in a_examiner if f.id not in payees]

    ecart = sum(
        (nouveau_montant - Decimal(str(f.amount)) for f in a_mettre_a_jour),
        Decimal("0"),
    )

    return _Repartition(
        a_mettre_a_jour=tuple(a_mettre_a_jour),
        deja_a_jour=len(deja_a_jour),
        conservees_car_payees=len(conservees),
        exonerees=len(exonerees),
        ecart_de_dette=ecart,
    )


def _phrase_ecart(ecart: Decimal, *, accompli: bool) -> str:
    """L'écart de dette, dit en francs et dans le bon sens."""
    if ecart == 0:
        return ""
    montant = f"{abs(ecart):,.0f}".replace(",", " ")
    if accompli:
        verbe = "a augmenté" if ecart > 0 else "a baissé"
    else:
        verbe = "augmenterait" if ecart > 0 else "baisserait"
    return f" La dette totale {verbe} de {montant} F."


def _message(repartition: _Repartition, *, accompli: bool) -> str:
    """Ce que l'école lit : des lignes comptées, jamais un « c'est fait »."""
    if repartition.concernees == 0:
        return "Aucune inscription ne porte ce tarif pour cette année. Il n'y a rien à répercuter."

    libelle_maj = (
        ("ligne mise à jour", "lignes mises à jour")
        if accompli
        else ("ligne à mettre à jour", "lignes à mettre à jour")
    )
    paquets = [
        Dependent(*libelle_maj, len(repartition.a_mettre_a_jour)),
        Dependent(
            "ligne conservée car un versement y est imputé",
            "lignes conservées car des versements y sont imputés",
            repartition.conservees_car_payees,
        ),
        Dependent(
            "ligne déjà au bon montant",
            "lignes déjà au bon montant",
            repartition.deja_a_jour,
        ),
        Dependent("ligne exonérée", "lignes exonérées", repartition.exonerees),
    ]
    detail = ", ".join(p.phrase() for p in paquets if p.count)
    return f"{detail}.{_phrase_ecart(repartition.ecart_de_dette, accompli=accompli)}"


async def preview_variant_propagation(db: AsyncSession, variant_id: int) -> FeePropagationPreview:
    """L'impact chiffré de la répercussion, sans rien écrire.

    Se lit avant de décider, et annonce exactement ce que la confirmation
    fera : les deux passent par la même répartition.
    """
    variant = await _load_variant(db, variant_id)
    repartition = await _repartir(db, variant)

    return FeePropagationPreview(
        variant_id=variant.id,
        fee_category_id=variant.fee_category_id,
        category_name=await _category_name(db, variant.fee_category_id),
        academic_year_id=variant.academic_year_id,
        amount=Decimal(str(variant.amount)),
        enrollments_concerned=repartition.concernees,
        fees_to_update=len(repartition.a_mettre_a_jour),
        fees_already_up_to_date=repartition.deja_a_jour,
        fees_kept_with_payments=repartition.conservees_car_payees,
        fees_waived=repartition.exonerees,
        debt_delta=repartition.ecart_de_dette,
        message=_message(repartition, accompli=False),
    )


async def apply_variant_propagation(
    db: AsyncSession, variant_id: int, *, applied_by: int
) -> FeePropagationResult:
    """Écrit le nouveau montant sur les lignes que l'aperçu annonçait.

    Le décompte rendu est celui des lignes réellement réécrites, pas celui
    qu'on espérait : c'est ce chiffre-là que l'école montrera si on lui
    demande des comptes.
    """
    variant = await _load_variant(db, variant_id)
    repartition = await _repartir(db, variant)

    nouveau_montant = Decimal(str(variant.amount))
    for ligne in repartition.a_mettre_a_jour:
        ligne.amount = nouveau_montant
    await db.flush()

    await audit_log(
        db,
        entity_type="fee_variant",
        action=AuditAction.UPDATE,
        user_id=applied_by,
        entity_id=variant.id,
        new_values={
            "action": "propagate_to_enrollments",
            "fee_category_id": variant.fee_category_id,
            "academic_year_id": variant.academic_year_id,
            "amount": str(nouveau_montant),
            "enrollments_concerned": repartition.concernees,
            "fees_updated": len(repartition.a_mettre_a_jour),
            "fees_already_up_to_date": repartition.deja_a_jour,
            "fees_kept_with_payments": repartition.conservees_car_payees,
            "fees_waived": repartition.exonerees,
            "debt_delta": str(repartition.ecart_de_dette),
        },
    )

    return FeePropagationResult(
        variant_id=variant.id,
        fee_category_id=variant.fee_category_id,
        category_name=await _category_name(db, variant.fee_category_id),
        academic_year_id=variant.academic_year_id,
        amount=nouveau_montant,
        enrollments_concerned=repartition.concernees,
        fees_updated=len(repartition.a_mettre_a_jour),
        fees_already_up_to_date=repartition.deja_a_jour,
        fees_kept_with_payments=repartition.conservees_car_payees,
        fees_waived=repartition.exonerees,
        debt_delta=repartition.ecart_de_dette,
        message=_message(repartition, accompli=True),
    )
