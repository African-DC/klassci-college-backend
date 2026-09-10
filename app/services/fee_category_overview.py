"""Quel frais rentre mal — la question qu'on pose AVANT d'en choisir un.

Le point par catégorie (`fee_category_ledger`) répond très bien à « où en est
la Tenue », à condition de savoir déjà que c'est la Tenue qui va mal. L'écran
exige donc une catégorie avant d'afficher quoi que ce soit, et le comptable
doit deviner : il ouvre la Scolarité, elle rentre bien, il ouvre la Cantine,
elle rentre bien, il ouvre la Tenue au bout de six essais. Ce module rend la
ligne par catégorie qui rendait ces six essais inutiles.

## Il ne rejoue pas le point, il partage son addition

Une ligne par catégorie, ce ne sont pas N points chargés à la suite. Charger
`load_category_ledger` en boucle relirait N fois la même table pour n'en garder
que les totaux, et — plus grave — laisserait deux totaux vivre côte à côte.
Ici la lecture est groupée une fois pour toutes les catégories, et l'addition
est celle du point, `fee_category_ledger.totaliser`, appelée par groupe. Le
taux d'une carte et le taux du document qu'elle ouvre sortent donc du même
code : ils ne peuvent pas se contredire.

## La ligne de partage, la même que partout

**Ce qui est entré se cloisonne. Ce qui reste dû ne se cloisonne pas.**

Une caissière lit, catégorie par catégorie, ce qu'elle a encaissé : c'est un
fait sur sa caisse, et c'est même le point qu'elle fait le soir. Elle ne lit ni
l'attendu, ni le taux, ni les compteurs par seau — ils se calculent sur tout
l'argent reçu, et sur une seule caisse ils annonceraient une dette chez des
familles ayant payé au guichet d'à côté. Ils sont donc ABSENTS, jamais
approchés, jamais mis à zéro : un zéro se lirait comme un solde.

L'écran doit le dire en toutes lettres. Une grille de tirets sans un mot se
lit comme une panne, et c'est la moitié des utilisateurs.

## Ce que cette vue ne montre pas, et pourquoi

Une catégorie qu'aucune ligne de frais ne porte sur ce périmètre n'y figure
pas. Ce n'est pas un frais qui rentre mal : c'est un frais qui n'a pas été
posé, et l'outil qui répond à celui-là existe déjà — `fee_propagation` compte
les lignes manquantes d'un tarif et dit ce que les créer ajouterait. Le
distinguer importe : « personne n'a payé la Cantine » et « personne n'a été
facturé pour la Cantine » appellent deux gestes opposés.

À l'intérieur d'une catégorie facturée, en revanche, l'élève sans ligne est
compté et rendu : c'est lui qui faisait rétrécir le dénominateur en silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import EnrollmentFee, FeeCategory
from app.services import fee_category_ledger, fees_paid


@dataclass(frozen=True, slots=True)
class LigneCategorie:
    """Une catégorie de frais, et comment elle rentre."""

    category_id: int
    category_name: str
    #: Faux, le compte de dépôts n'a pas lieu d'être affiché sur cette carte.
    accepts_in_kind: bool
    #: Un frais facultatif qui rentre mal n'appelle pas la même relance qu'une
    #: scolarité : l'écran doit pouvoir le dire sans reposer la question.
    is_mandatory: bool

    #: Combien d'inscriptions du périmètre cette catégorie facture, et combien
    #: elle en laisse de côté. Ce sont des inscriptions, pas de l'argent : ils
    #: ne se cloisonnent pas.
    eleves_factures: int
    eleves_sans_ligne: int

    #: Ce qui est ENTRÉ, cloisonné par caisse et borné par la période.
    eleves_en_argent: int
    total_en_argent: Decimal
    depots_en_nature: int

    #: L'outil de recouvrement. `None` sans le droit de lire toutes les
    #: caisses : ces chiffres se lisent sur tout l'argent reçu, et l'absence
    #: vaut mieux qu'un chiffre faux.
    eleves_restant_du: int | None
    total_restant_du: Decimal | None
    total_attendu: Decimal | None
    taux_recouvrement: float | None
    compteurs: dict[str, int] | None


@dataclass(frozen=True, slots=True)
class CategoriesOverview:
    """La vue d'ensemble : le périmètre lu, et une ligne par catégorie."""

    academic_year_id: int
    class_id: int | None
    #: Le nom du périmètre, lu depuis le CRITÈRE et non depuis les lignes :
    #: une classe sans aucune ligne de frais a quand même un nom, et c'est
    #: précisément le moment où le document doit le dire.
    class_name: str
    date_from: datetime | None
    date_to: datetime | None
    #: Vrai quand le lecteur voit toutes les caisses. Faux, chaque ligne ne
    #: porte que ce qu'il a lui-même encaissé, et rien du reste dû.
    consolide: bool

    #: Les inscriptions ouvertes du périmètre — le dénominateur commun à
    #: toutes les catégories, et la raison pour laquelle il est porté ici et
    #: non recopié sur chaque ligne.
    effectif_perimetre: int

    categories: tuple[LigneCategorie, ...]


async def load_categories_overview(
    db: AsyncSession,
    *,
    academic_year_id: int,
    class_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    received_by: int | None = None,
    consolide: bool = True,
) -> CategoriesOverview:
    """Compose la vue d'ensemble : une ligne par catégorie facturée.

    `academic_year_id` est OBLIGATOIRE, comme sur le point qu'une carte ouvre.
    Sans lui, l'attendu et le taux additionneraient tous les exercices de la
    base : une école de cinq ans d'ancienneté afficherait un taux de
    recouvrement mêlant des dettes prescrites à celles de l'année en cours, et
    la carte n'annoncerait pas le même total que le document qu'elle ouvre.

    `received_by` restreint à une caisse **tout ce qui est entré** : l'argent
    versé et les dépôts en nature. C'est `cashier_scope` qui le décide en
    amont, jamais ce module — la règle du cloisonnement vit à un seul endroit.

    `consolide` dit si l'appelant lit toutes les caisses. Sans ce droit, le
    reste dû, l'attendu, le taux et les compteurs ne sont pas calculés du tout.

    QUATRE requêtes, quel que soit le nombre de catégories : les lignes du
    périmètre, le versé de la période, le versé sans bornes, et l'effectif —
    plus une cinquième, minuscule, pour les noms des catégories rencontrées.
    Une par catégorie ferait relire la même table autant de fois qu'il y a de
    frais, sur un écran qui s'ouvre à chaque consultation.
    """
    inscriptions_conditions = [
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status.not_in(CLOSED_STATUSES),
    ]
    if class_id is not None:
        inscriptions_conditions.append(Enrollment.class_id == class_id)

    # LE PERIMETRE ENTIER, toutes categories confondues, en colonnes nues :
    # ce qu'on additionne ici, ce sont des montants et des statuts. Les noms
    # sont charges a part, une fois par categorie et non une fois par eleve.
    perimetre = (
        await db.execute(
            select(
                EnrollmentFee.id,
                EnrollmentFee.fee_category_id,
                EnrollmentFee.amount,
                EnrollmentFee.status,
                EnrollmentFee.deposited_at,
                EnrollmentFee.deposited_by_user_id,
            )
            .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
            .where(*inscriptions_conditions)
        )
    ).all()

    # L'EVENEMENT et l'ETAT, chacun en une requete groupee pour toute l'annee.
    # Bornees par le perimetre et non par une liste d'identifiants : l'ecole
    # entiere fois ses categories ferait des milliers de valeurs dans un
    # `IN (...)`. Le calcul lui-meme vit dans `fees_paid`, seul detenteur
    # declare de la regle de l'argent.
    verse = await fees_paid.paid_by_fee_for_scope(
        db,
        academic_year_id=academic_year_id,
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        received_by=received_by,
    )
    verse_total: dict[int, Decimal] = {}
    if consolide:
        verse_total = await fees_paid.paid_by_fee_for_scope(
            db, academic_year_id=academic_year_id, class_id=class_id
        )

    # L'effectif ne se cloisonne pas : ce sont des inscriptions, pas de
    # l'argent. Une caissiere a le droit de savoir combien d'eleves son
    # point aurait du couvrir.
    effectif = int(
        (
            await db.execute(
                select(func.count()).select_from(Enrollment).where(*inscriptions_conditions)
            )
        ).scalar_one()
        or 0
    )

    par_categorie: dict[int, list[Any]] = {}
    for row in perimetre:
        par_categorie.setdefault(int(row.fee_category_id), []).append(row)

    categories = await _categories_rencontrees(db, list(par_categorie))

    lignes: list[LigneCategorie] = []
    for categorie in categories:
        groupe = par_categorie[categorie.id]
        # LA MEME ADDITION QUE LE POINT, appelee sur le groupe. Un second
        # calcul ici ferait diverger la carte du document qu'elle ouvre, et
        # c'est le genre d'ecart qu'on ne remarque qu'une fois le total envoye
        # a un prestataire.
        totaux = fee_category_ledger.totaliser(
            groupe,
            verse=verse,
            verse_total=verse_total,
            consolide=consolide,
            received_by=received_by,
            date_from=date_from,
            date_to=date_to,
        )
        lignes.append(
            LigneCategorie(
                category_id=categorie.id,
                category_name=categorie.name,
                accepts_in_kind=bool(categorie.accepts_in_kind),
                is_mandatory=bool(categorie.is_mandatory),
                # `uq_enrollment_fee_category` garantit une ligne par
                # inscription et par categorie : compter les lignes du groupe,
                # c'est compter les eleves qu'elles couvrent.
                eleves_factures=len(groupe),
                eleves_sans_ligne=max(effectif - len(groupe), 0),
                eleves_en_argent=totaux.eleves_en_argent,
                total_en_argent=totaux.total_en_argent,
                depots_en_nature=totaux.depots_en_nature,
                eleves_restant_du=totaux.eleves_restant_du,
                total_restant_du=totaux.total_restant_du,
                total_attendu=totaux.total_attendu,
                taux_recouvrement=totaux.taux_recouvrement,
                compteurs=totaux.compteurs,
            )
        )

    return CategoriesOverview(
        academic_year_id=academic_year_id,
        class_id=class_id,
        class_name=await fee_category_ledger.nom_du_perimetre(db, class_id),
        date_from=date_from,
        date_to=date_to,
        consolide=consolide,
        effectif_perimetre=effectif,
        categories=tuple(lignes),
    )


async def _categories_rencontrees(db: AsyncSession, ids: list[int]) -> list[FeeCategory]:
    """Les catégories du périmètre, dans l'ordre que l'école a configuré.

    L'ordre est celui de `priority` — la convention d'imputation de
    l'établissement : Inscription, puis les trimestres, puis le reste. Trier
    par taux serait tentant, puisque la question posée est « lequel rentre le
    plus mal » ; ce serait aussi rendre l'ordre des cartes dépendant des droits
    du lecteur, une caissière n'ayant aucun taux. Deux personnes décrivant leur
    écran au téléphone ne verraient pas la même chose au même endroit. Le tri
    par ce qui va mal est un geste d'écran, et il se fait sur des chiffres que
    la réponse porte déjà.

    Les identifiants viennent des lignes déjà lues : la liste est courte, une
    école n'ayant pas cent catégories de frais.
    """
    if not ids:
        return []
    stmt = (
        select(FeeCategory)
        .where(FeeCategory.id.in_(ids))
        .order_by(FeeCategory.priority, FeeCategory.name, FeeCategory.id)
    )
    return list((await db.execute(stmt)).scalars().all())
