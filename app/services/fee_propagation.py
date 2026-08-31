"""Répercuter un tarif sur les inscriptions de son année : deux gestes distincts.

Changer le montant d'un tarif ne touchait pas les élèves déjà inscrits. Leur
dette gardait l'ancien montant, sans que rien ne le dise : une école qui
corrigeait une erreur de saisie voyait sa grille afficher 45 000 et ses
familles continuer de devoir 54 000.

**Le geste par défaut : réécrire, et seulement réécrire.** Le module met à
jour **les lignes qui portent ce tarif-là**, pour l'année de ce tarif. Il ne
régénère pas la grille d'une inscription et il ne crée aucune ligne :
corriger une faute de frappe sur le prix de la tenue ne doit ajouter de dette
à personne. C'est le comportement qu'on obtient sans rien demander de plus,
et il est resté exactement celui d'avant.

**Le second geste, demandé explicitement : créer les lignes manquantes.** Une
école qui ajoute le tarif d'entrée des nouveaux après la rentrée ne veut pas
ressaisir six cents dossiers à la main. `create_missing`, dans le corps du
POST, ouvre cette création, et rien d'autre ne l'ouvre. L'aperçu, lui, compte
toujours ces lignes manquantes : l'école doit VOIR l'occasion, même le jour
où elle ne la saisit pas.

**Une ligne créée vaut ce que l'inscription aurait payé.** La création
n'applique pas le tarif répercuté parce qu'il « peut » atteindre
l'inscription : elle ne l'applique que s'il est le plus spécifique de sa
catégorie pour cette inscription-là, exactement comme
`most_specific_variant_per_category` en décide au guichet. Sans cet arbitrage,
répercuter un tarif général à 50 000 sur un élève que la grille destine au
tarif « nouveau » à 75 000 poserait la mauvaise somme, et
`uq_enrollment_fee_category` interdirait ensuite la bonne : l'erreur serait
définitive.

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
from app.models.academic import Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    PaymentAllocation,
    is_in_kind,
    is_not_cash_due,
)
from app.schemas.fee import FeePropagationPreview, FeePropagationResult
from app.services import enrollment_fees
from app.services.deletion import Dependent

#: Une inscription refusée ou annulée ne doit plus rien : sa dette est close,
#: la relancer à la hausse ferait réapparaître un impayé sur un dossier clos.
_STATUTS_HORS_JEU = (EnrollmentStatus.REJETE, EnrollmentStatus.ANNULE)


@dataclass(frozen=True, slots=True)
class _Repartition:
    """Les lignes concernées, rangées par ce qui va leur arriver.

    Les cinq paquets forment une partition : leur somme est le nombre
    d'inscriptions concernées. Sans cela l'aperçu afficherait un total que
    son propre détail contredit, et c'est le genre d'écart qui fait douter
    de tout le reste de l'écran.

    Les quatre premiers rangent des lignes qui portent déjà ce tarif. Le
    cinquième, `a_creer`, range des inscriptions qui n'en portent aucune :
    l'école vient d'ajouter un tarif d'entrée par-dessus sa grille, et les
    élèves déjà inscrits ne l'ont jamais reçu. Les cinq restent disjoints par
    construction : une inscription qui porte une ligne de cette catégorie
    n'entre jamais dans `a_creer`.

    `a_creer` reste vide quand la création n'est pas demandée. Le total, le
    détail et l'écart de dette décrivent alors le seul geste qui va avoir
    lieu, et personne ne lit un chiffre qui ne se produira pas.

    Les deux écarts de dette sont tenus séparés parce qu'ils ne se décident
    pas ensemble : réécrire est le geste par défaut, créer se demande. Les
    additionner d'office ferait annoncer, sur un aperçu, une dette que le
    bouton ne créera pas.
    """

    a_mettre_a_jour: tuple[EnrollmentFee, ...]
    a_creer: tuple[Enrollment, ...]
    deja_a_jour: int
    conservees_car_payees: int
    exonerees: int
    #: Lignes reglees par un depot d'article. Elles ne doivent rien en argent,
    #: comme les exonerees, mais un depot n'est pas une exoneration DRENA et ne
    #: doit donc pas gonfler `fees_waived`. Elles ont pourtant leur place dans
    #: la partition : sans ce paquet elles n'appartenaient a aucun des cinq, et
    #: le total annonce etait inferieur au nombre reel d'inscriptions touchees,
    #: exactement le total que son propre detail contredit.
    deposees_en_nature: int
    #: Ce que les seules réécritures déplacent, négatif quand le tarif baisse.
    ecart_des_reecritures: Decimal
    #: Ce que les lignes manquantes ajouteraient, si on les crée.
    ecart_des_creations: Decimal

    @property
    def concernees(self) -> int:
        return (
            len(self.a_mettre_a_jour)
            + len(self.a_creer)
            + self.deja_a_jour
            + self.conservees_car_payees
            + self.exonerees
            + self.deposees_en_nature
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


async def _est_obligatoire(db: AsyncSession, category_id: int) -> bool:
    """Cette catégorie s'impose-t-elle, ou se souscrit-elle ?

    La cantine se souscrit, elle ne s'impose pas : créer d'office une ligne
    pour un frais optionnel abonnerait toute une école au transport scolaire
    parce que quelqu'un a ajusté son prix. `create_mandatory_enrollment_fees`
    pose déjà ce filtre à l'inscription ; la répercussion, qui écrit les mêmes
    lignes, le pose pour la même raison.
    """
    obligatoire = (
        await db.execute(select(FeeCategory.is_mandatory).where(FeeCategory.id == category_id))
    ).scalar_one_or_none()
    return bool(obligatoire)


async def _tarifs_concurrents(db: AsyncSession, variant: FeeVariant) -> list[FeeVariant]:
    """Les tarifs qui peuvent disputer une inscription à celui qu'on répercute.

    Même catégorie, même année, même niveau : ce sont exactement ceux que
    `get_mandatory_fee_variants` mettrait en concurrence au guichet, puisque
    toutes les inscriptions candidates sont de ce niveau-là et qu'un frais
    obligatoire exige le niveau à l'identique.

    Chargés une fois pour toute la cohorte, puis arbitrés en mémoire : poser
    la question par élève ferait six cents requêtes derrière un seul bouton.
    """
    stmt = (
        select(FeeVariant)
        .where(
            FeeVariant.fee_category_id == variant.fee_category_id,
            FeeVariant.academic_year_id == variant.academic_year_id,
            FeeVariant.level_id == variant.level_id,
        )
        .order_by(FeeVariant.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _a_creer(db: AsyncSession, variant: FeeVariant) -> list[Enrollment]:
    """Les inscriptions auxquelles ce tarif, et pas un autre, doit sa ligne manquante.

    Une école qui ajoute le tarif d'entrée des nouveaux après la rentrée ne
    veut pas ressaisir six cents dossiers à la main. Encore faut-il écrire le
    montant que le guichet aurait écrit.

    Il ne suffit donc PAS que le tarif puisse atteindre l'inscription :
    `variant_applies_to` reproduit le WHERE de `get_mandatory_fee_variants`,
    mais pas l'arbitrage de spécificité que le chemin d'inscription applique
    juste après. Une catégorie Inscription portant un tarif général à 50 000 et
    un tarif « nouveau » à 75 000 atteint les deux fois une inscription
    déclarée nouvelle : répercuter le général y poserait 50 000 alors que le
    guichet y pose 75 000, et `uq_enrollment_fee_category` interdirait ensuite
    la bonne ligne. L'erreur serait définitive, et c'est une facture.

    On rejoue donc l'arbitrage complet, inscription par inscription, avec la
    fonction même dont dépendent les autres chemins d'écriture : une ligne
    n'est créée que si le tarif répercuté est le plus spécifique de sa
    catégorie pour cette inscription-là.

    Restent les gardes qui valaient déjà : la catégorie doit s'imposer,
    l'inscription ne doit porter aucune ligne de cette catégorie (sans quoi on
    recréerait le doublon que `uq_enrollment_fee_category` existe pour
    interdire), et les statuts hors jeu comme le filtre d'archivage
    s'appliquent comme partout ailleurs dans ce module.
    """
    if variant.level_id is None or not await _est_obligatoire(db, variant.fee_category_id):
        return []

    concurrents = await _tarifs_concurrents(db, variant)

    deja_facturee = (
        select(EnrollmentFee.id)
        .where(
            EnrollmentFee.enrollment_id == Enrollment.id,
            EnrollmentFee.fee_category_id == variant.fee_category_id,
        )
        .correlate(Enrollment)
        .exists()
    )
    stmt = (
        select(Enrollment, Class)
        .join(Class, Class.id == Enrollment.class_id)
        .where(
            Enrollment.academic_year_id == variant.academic_year_id,
            Enrollment.status.not_in(_STATUTS_HORS_JEU),
            Class.level_id == variant.level_id,
            ~deja_facturee,
        )
        .order_by(Enrollment.id)
    )

    retenues: list[Enrollment] = []
    for enrollment, class_ in (await db.execute(stmt)).all():
        applicables = [
            concurrent
            for concurrent in concurrents
            if enrollment_fees.variant_applies_to(
                concurrent,
                series_id=class_.series_id,
                assignment_status=enrollment.assignment_status,
                is_new_student=enrollment.is_new_student,
            )
        ]
        retenus = enrollment_fees.most_specific_variant_per_category(applicables)
        if any(retenu.id == variant.id for retenu in retenus):
            retenues.append(enrollment)
    return retenues


async def _repartir(db: AsyncSession, variant: FeeVariant, *, creations: bool) -> _Repartition:
    """Classe les lignes portant ce tarif selon ce qu'il faut leur faire.

    Le périmètre est volontairement étroit : les lignes rattachées à CE
    tarif, sur des inscriptions vivantes de l'année de CE tarif. Une
    inscription d'une autre année garde son montant, parce que sa facture a
    été émise sous une autre grille.

    `creations` dit si les lignes manquantes entrent dans la répartition.
    L'aperçu les demande toujours, pour montrer l'occasion à l'école ; la
    répercussion ne les demande que si on lui a réclamé de les créer. Ce qui
    n'est pas demandé n'est pas cherché : le geste par défaut reste, à la
    requête près, celui d'avant cette dimension.

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
    # Un dépôt en nature n'est pas une exonération DRENA : il ne gonfle ni
    # `fees_waived` ni la dette à répercuter. Il est compté à part, parce
    # qu'il reste une ligne touchée par ce tarif et que la partition doit
    # sommer juste.
    deposees = [f for f in lignes if is_in_kind(f.status)]
    dues = [f for f in lignes if not is_not_cash_due(f.status)]
    deja_a_jour = [f for f in dues if Decimal(str(f.amount)) == nouveau_montant]

    a_examiner = [f for f in dues if Decimal(str(f.amount)) != nouveau_montant]
    payees = await _fee_ids_with_allocations(db, [f.id for f in a_examiner])
    conservees = [f for f in a_examiner if f.id in payees]
    a_mettre_a_jour = [f for f in a_examiner if f.id not in payees]

    a_creer = await _a_creer(db, variant) if creations else []

    return _Repartition(
        a_mettre_a_jour=tuple(a_mettre_a_jour),
        a_creer=tuple(a_creer),
        deja_a_jour=len(deja_a_jour),
        conservees_car_payees=len(conservees),
        exonerees=len(exonerees),
        deposees_en_nature=len(deposees),
        ecart_des_reecritures=sum(
            (nouveau_montant - Decimal(str(f.amount)) for f in a_mettre_a_jour),
            Decimal("0"),
        ),
        # Une ligne créée ajoute son montant entier : elle n'existait pas.
        ecart_des_creations=nouveau_montant * len(a_creer),
    )


def _francs(montant: Decimal) -> str:
    """Un montant lisible par une comptable : espaces, pas de virgules."""
    return f"{abs(montant):,.0f}".replace(",", " ")


def _phrase_ecart(ecart: Decimal, *, accompli: bool) -> str:
    """L'écart de dette, dit en francs et dans le bon sens."""
    if ecart == 0:
        return ""
    if accompli:
        verbe = "a augmenté" if ecart > 0 else "a baissé"
    else:
        verbe = "augmenterait" if ecart > 0 else "baisserait"
    return f" La dette totale {verbe} de {_francs(ecart)} F."


def _phrase_creations(repartition: _Repartition) -> str:
    """Ce que créer les lignes manquantes coûterait, annoncé à part.

    À part, parce que ce n'est pas le même geste. L'écart annoncé juste avant
    est celui de la répercussion seule, celle que la confirmation fait par
    défaut ; créer les lignes manquantes se demande. Fondre les deux dans un
    seul chiffre ferait annoncer une dette que le geste par défaut ne créera
    pas, et l'école chercherait longtemps ce montant dans ses comptes.
    """
    if not repartition.a_creer:
        return ""
    montant = _francs(repartition.ecart_des_creations)
    return f" Créer les lignes manquantes ajouterait {montant} F."


def _message(repartition: _Repartition, *, accompli: bool, ecart: Decimal) -> str:
    """Ce que l'école lit : des lignes comptées, jamais un « c'est fait »."""
    if repartition.concernees == 0:
        return "Aucune inscription ne porte ce tarif pour cette année. Il n'y a rien à répercuter."

    libelle_maj = (
        ("ligne mise à jour", "lignes mises à jour")
        if accompli
        else ("ligne à mettre à jour", "lignes à mettre à jour")
    )
    # « manquante » et non « à créer » tant que rien n'est fait : la
    # confirmation ne les crée que si on le lui demande, et annoncer « à
    # créer » promettrait un geste que le bouton ne fait pas tout seul.
    libelle_creation = (
        ("ligne créée", "lignes créées") if accompli else ("ligne manquante", "lignes manquantes")
    )
    paquets = [
        Dependent(*libelle_maj, len(repartition.a_mettre_a_jour)),
        Dependent(*libelle_creation, len(repartition.a_creer)),
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
        Dependent(
            "ligne réglée par un dépôt",
            "lignes réglées par un dépôt",
            repartition.deposees_en_nature,
        ),
    ]
    detail = ", ".join(p.phrase() for p in paquets if p.count)
    suite = "" if accompli else _phrase_creations(repartition)
    return f"{detail}.{_phrase_ecart(ecart, accompli=accompli)}{suite}"


async def preview_variant_propagation(db: AsyncSession, variant_id: int) -> FeePropagationPreview:
    """L'impact chiffré de la répercussion, sans rien écrire.

    Se lit avant de décider, et annonce exactement ce que la confirmation
    fera : `debt_delta` est celui des seules réécritures, le geste que la
    confirmation fait par défaut.

    Les lignes manquantes sont comptées dans tous les cas, création demandée
    ou non : l'école doit voir que son tarif n'a jamais atteint ces élèves-là,
    même le jour où elle ne veut corriger qu'un montant. Ce qu'elles
    coûteraient est dit à part, dans le message, pour qu'aucun des deux
    chiffres ne se fasse passer pour l'autre.
    """
    variant = await _load_variant(db, variant_id)
    repartition = await _repartir(db, variant, creations=True)

    return FeePropagationPreview(
        variant_id=variant.id,
        fee_category_id=variant.fee_category_id,
        category_name=await _category_name(db, variant.fee_category_id),
        academic_year_id=variant.academic_year_id,
        amount=Decimal(str(variant.amount)),
        enrollments_concerned=repartition.concernees,
        fees_to_update=len(repartition.a_mettre_a_jour),
        fees_to_create=len(repartition.a_creer),
        fees_already_up_to_date=repartition.deja_a_jour,
        fees_kept_with_payments=repartition.conservees_car_payees,
        fees_waived=repartition.exonerees,
        fees_in_kind=repartition.deposees_en_nature,
        debt_delta=repartition.ecart_des_reecritures,
        message=_message(repartition, accompli=False, ecart=repartition.ecart_des_reecritures),
    )


async def apply_variant_propagation(
    db: AsyncSession, variant_id: int, *, applied_by: int, create_missing: bool = False
) -> FeePropagationResult:
    """Écrit les montants corrigés, et les lignes manquantes si on l'a demandé.

    `create_missing` reste faux par défaut, et ce défaut est le geste d'avant
    cette dimension : aucune ligne créée, aucune dette ajoutée à personne.
    Corriger une faute de frappe sur le prix de la tenue ne doit endetter
    aucune famille de plus.

    Le décompte rendu est celui des lignes réellement réécrites et créées, pas
    celui qu'on espérait : c'est ce chiffre-là que l'école montrera si on lui
    demande des comptes. `debt_delta` suit la même règle et ne chiffre que ce
    que cet appel a écrit.
    """
    variant = await _load_variant(db, variant_id)
    repartition = await _repartir(db, variant, creations=create_missing)
    # Sans création demandée, `a_creer` est vide et son écart nul : la somme
    # décrit alors les seules réécritures, comme avant.
    ecart = repartition.ecart_des_reecritures + repartition.ecart_des_creations

    nouveau_montant = Decimal(str(variant.amount))
    for ligne in repartition.a_mettre_a_jour:
        ligne.amount = nouveau_montant
    for inscription in repartition.a_creer:
        db.add(
            EnrollmentFee(
                enrollment_id=inscription.id,
                fee_variant_id=variant.id,
                # Recopiée du tarif : c'est elle que porte la contrainte
                # `uq_enrollment_fee_category`, une catégorie par inscription.
                fee_category_id=variant.fee_category_id,
                amount=nouveau_montant,
            )
        )
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
            # Deux gestes derrière un même bouton : la trace doit dire lequel
            # a été demandé, sinon on ne saura plus qui a créé ces dettes.
            "create_missing": create_missing,
            "enrollments_concerned": repartition.concernees,
            "fees_updated": len(repartition.a_mettre_a_jour),
            "fees_created": len(repartition.a_creer),
            "fees_already_up_to_date": repartition.deja_a_jour,
            "fees_kept_with_payments": repartition.conservees_car_payees,
            "fees_waived": repartition.exonerees,
            "fees_in_kind": repartition.deposees_en_nature,
            "debt_delta": str(ecart),
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
        fees_created=len(repartition.a_creer),
        fees_already_up_to_date=repartition.deja_a_jour,
        fees_kept_with_payments=repartition.conservees_car_payees,
        fees_waived=repartition.exonerees,
        fees_in_kind=repartition.deposees_en_nature,
        debt_delta=ecart,
        message=_message(repartition, accompli=True, ecart=ecart),
    )
