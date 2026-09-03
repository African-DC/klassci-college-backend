"""Le point sur une catégorie de frais : ce qui est entré, ce qui manque.

Une vue detaillee sur **un** frais, la ou le reste de l'application regarde un
eleve ou une classe. Elle vaut pour n'importe quelle categorie — inscription,
scolarite, tenue, paquet de rames — et chaque metier y lit autre chose.

Le cas qui l'a fait naitre est celui d'un article fourni par un prestataire.
Le comptable a besoin de deux chiffres que rien ne donnait :

- **ce qui est entre en argent**, pour savoir ce qu'il envoie au fournisseur ;
- **ce qui est entre en nature**, pour verifier que le stock correspond aux
  articles reellement remis.

Sur une scolarite, les memes colonnes repondent a une autre question : combien
est rentre sur la periode, et qui n'a pas encore paye. C'est le meme document,
et c'est pour ca qu'il n'est pas ecrit pour les rames.

Il lui faut les noms dans tous les cas, parce qu'un total qu'on ne peut pas
rouvrir ne se defend ni devant un fournisseur ni devant un parent.

## La ligne de partage, qui commande tout le reste

**Ce qui est entre se cloisonne. Ce qui reste du ne se cloisonne pas.**

Une caissiere lit ce qu'elle a encaisse : c'est un fait sur sa caisse, vrai
quel que soit le reste. Le lui refuser l'empecherait de faire son point.

Ce qu'une famille doit encore, en revanche, se calcule sur tout l'argent recu,
quel que soit le guichet. Filtre sur une seule caisse, ce chiffre annoncerait
une dette chez une famille qui a paye a cote — et on irait la relancer. Il est
donc reserve a qui lit deja toutes les caisses, et absent, plutot que faux,
pour les autres.

## Ce que la periode borne, et ce qu'elle ne borne pas

Un versement et un depot sont des **evenements** : ils ont une date, et se
bornent. Ce qui reste du est un **etat** : il vaut a l'instant ou on regarde,
et le borner n'aurait aucun sens. Le document le dit, plutot que de laisser
croire que la colonne des impayes parle du mois choisi.

## Une precision sur les quantites

L'application enregistre un depot **par ligne de frais**, pas une quantite :
une ligne est deposee ou elle ne l'est pas. « Douze depots » veut donc dire
douze eleves ayant remis ce que leur ligne demandait, et non douze paquets si
une ligne en vaut deux. Le document parle de depots, jamais de paquets, pour
ne pas promettre un decompte que la base ne tient pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    cash_remaining,
)
from app.models.user import Student
from app.services import fees_paid


@dataclass(frozen=True, slots=True)
class LigneEleve:
    """Un élève, et où il en est sur cette catégorie."""

    enrollment_id: int
    student_id: int
    first_name: str
    last_name: str
    student_matricule: str | None
    class_name: str
    #: `paid`, `partial`, `pending`, `in_kind`, `waived`.
    #:
    #: Recopié de `EnrollmentFee.status`, qui est recalculé sur **tout**
    #: l'argent reçu (`payments._allocation.recompute_fee_status`). Ne pas le
    #: dériver de `paid` : ce montant-là est celui d'une seule caisse quand
    #: l'appelant est cloisonné, et une ligne qu'une collègue a soldée
    #: ressortirait « partiel ». C'est la dette fantôme que ce module refuse
    #: déjà pour `remaining`, et elle rentrerait par la porte du badge.
    status: str
    due: Decimal
    #: Ce qui est entré en argent sur la période demandée.
    paid: Decimal
    #: Ce qui reste dû aujourd'hui. `None` quand l'appelant n'a pas le droit
    #: de le savoir : absent vaut mieux que faux.
    remaining: Decimal | None
    deposited_at: datetime | None


@dataclass(frozen=True, slots=True)
class CategoryLedger:
    """Le document entier."""

    category_id: int
    category_name: str
    accepts_in_kind: bool
    class_name: str
    date_from: datetime | None
    date_to: datetime | None
    #: Vrai quand le lecteur voit toutes les caisses. Faux, le document ne
    #: porte que ce qu'il a lui-même encaissé, et ne dit rien des impayés.
    consolide: bool

    #: Ce qui est entré en argent sur la période — ce qu'on envoie au prestataire.
    eleves_en_argent: int
    total_en_argent: Decimal
    #: Ce qui est entré en nature sur la période — ce qu'on doit retrouver en stock.
    depots_en_nature: int
    #: L'état, pas un événement : jamais borné par la période, et `None` sans
    #: le droit de lire toutes les caisses.
    eleves_restant_du: int | None
    total_restant_du: Decimal | None

    lignes: tuple[LigneEleve, ...]


async def load_category_ledger(
    db: AsyncSession,
    *,
    category_id: int,
    academic_year_id: int,
    class_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    received_by: int | None = None,
    consolide: bool = True,
) -> CategoryLedger:
    """Compose le point d'une catégorie.

    `received_by` restreint à une caisse **tout ce qui est entré** : l'argent
    versé et les dépôts en nature. C'est `cashier_scope` qui le décide en
    amont, et non ce module : la règle du cloisonnement vit à un seul
    endroit, et la redécider ici finirait par en donner deux versions.

    Le compte des dépôts ne l'a pas toujours respecté, et le document
    rendait alors le total de l'école entière à une caissière — sous une
    phrase affirmant qu'il ne couvrait que sa caisse. Un document qui se
    contredit sur son propre périmètre vaut moins que pas de document.

    `consolide` dit si l'appelant a le droit de lire toutes les caisses. Sans
    lui, le reste dû n'est pas calculé du tout — pas mis à zéro, pas approché :
    absent.

    Le versé ne se calcule pas ici : `fees_paid.paid_by_fee_ids` le fait, une
    fois avec la fenêtre et la caisse (l'événement), une fois sans (l'état).
    Ce module en portait sa propre copie, filtre `completed` compris.
    """
    categorie = (
        await db.execute(select(FeeCategory).where(FeeCategory.id == category_id))
    ).scalar_one_or_none()

    inscriptions_conditions = [
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status.not_in(CLOSED_STATUSES),
    ]
    if class_id is not None:
        inscriptions_conditions.append(Enrollment.class_id == class_id)

    # Les lignes de frais de cette catégorie, sur le périmètre demandé.
    stmt = (
        select(EnrollmentFee)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(EnrollmentFee.fee_category_id == category_id, *inscriptions_conditions)
        .options(
            selectinload(EnrollmentFee.enrollment).selectinload(Enrollment.student),
            selectinload(EnrollmentFee.enrollment).selectinload(Enrollment.class_),
        )
        .order_by(Student.last_name, Student.first_name, EnrollmentFee.id)
    )
    frais = list((await db.execute(stmt)).scalars().all())

    fee_ids = [f.id for f in frais]
    # L'EVENEMENT : ce qui est entre dans la fenetre, sur cette caisse. Le
    # calcul lui-meme vit dans `fees_paid`, seul detenteur declare de la regle
    # de l'argent — il a deja ete recopie ici, et deux exemplaires d'une meme
    # somme finissent toujours par diverger.
    verse = await fees_paid.paid_by_fee_ids(
        db,
        fee_ids=fee_ids,
        date_from=date_from,
        date_to=date_to,
        received_by=received_by,
    )
    # L'ETAT : le meme appel sans bornes ni caisse. Le reste du se calcule sur
    # tout l'argent recu — une famille qui a paye le mois dernier ne doit rien
    # ce mois-ci, et une famille qui a paye au guichet d'a cote ne doit rien
    # non plus. Groupee, comme la premiere : la demander ligne par ligne
    # couterait une requete par eleve sur un ecran qui les montre tous.
    verse_total = await fees_paid.paid_by_fee_ids(db, fee_ids=fee_ids) if consolide else {}

    lignes: list[LigneEleve] = []
    eleves_en_argent = 0
    total_en_argent = Decimal("0")
    depots = 0
    eleves_du = 0
    total_du = Decimal("0")

    for ligne in frais:
        inscription = ligne.enrollment
        eleve = inscription.student
        statut = str(getattr(ligne.status, "value", ligne.status))
        montant = Decimal(str(ligne.amount or 0))
        paye = verse.get(ligne.id, Decimal("0"))

        if paye > 0:
            eleves_en_argent += 1
            total_en_argent += paye

        # Un depot est quelque chose qui est ENTRE : il se cloisonne donc comme
        # l'argent. `received_by` ne filtrait que les versements, et ce compte
        # rendait a une caissiere le total de toute l'ecole sous un document
        # qui affirme en toutes lettres ne couvrir que sa caisse.
        depose = statut == EnrollmentFeeStatus.IN_KIND.value
        de_ma_main = received_by is None or ligne.deposited_by_user_id == received_by
        if depose and de_ma_main and _dans_la_fenetre(ligne.deposited_at, date_from, date_to):
            depots += 1

        reste: Decimal | None = None
        if consolide:
            # Sur tout l'argent recu, jamais sur la fenetre : une famille qui a
            # paye le mois dernier ne doit rien ce mois-ci.
            reste = cash_remaining(statut, montant, verse_total.get(ligne.id, Decimal("0")))
            if reste > 0:
                eleves_du += 1
                total_du += reste

        lignes.append(
            LigneEleve(
                enrollment_id=inscription.id,
                student_id=eleve.id,
                first_name=eleve.first_name,
                last_name=eleve.last_name,
                student_matricule=getattr(eleve, "enrollment_number", None),
                class_name=getattr(inscription.class_, "name", "") or "",
                status=statut,
                due=montant,
                paid=paye,
                remaining=reste,
                deposited_at=ligne.deposited_at,
            )
        )

    return CategoryLedger(
        category_id=category_id,
        category_name=getattr(categorie, "name", "") or f"Catégorie {category_id}",
        accepts_in_kind=bool(getattr(categorie, "accepts_in_kind", False)),
        class_name="Toutes les classes" if class_id is None else _nom_de_classe(frais),
        date_from=date_from,
        date_to=date_to,
        consolide=consolide,
        eleves_en_argent=eleves_en_argent,
        total_en_argent=total_en_argent,
        depots_en_nature=depots,
        eleves_restant_du=eleves_du if consolide else None,
        total_restant_du=total_du if consolide else None,
        lignes=tuple(lignes),
    )


def _nom_de_classe(frais: list[EnrollmentFee]) -> str:
    for ligne in frais:
        nom = getattr(getattr(ligne.enrollment, "class_", None), "name", "")
        if nom:
            return nom
    return ""


def _dans_la_fenetre(
    quand: datetime | None, date_from: datetime | None, date_to: datetime | None
) -> bool:
    """Un dépôt sans date compte comme hors période : on ne devine pas."""
    if quand is None:
        return date_from is None and date_to is None
    if date_from is not None and quand < date_from:
        return False
    if date_to is not None and quand >= date_to:
        return False
    return True


async def get_category_ledger_xlsx(
    db: AsyncSession,
    *,
    category_id: int,
    academic_year_id: int,
    class_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    received_by: int | None = None,
    consolide: bool = True,
) -> bytes:
    """Le même document, au gabarit officiel de l'établissement.

    La signature est recopiée plutôt que passée en `**kwargs` : un classeur qui
    perdrait `consolide` en chemin sortirait sans son avertissement, et c'est
    la ligne qui empêche de prendre un document de guichet pour le compte de
    l'école entière.

    Import local, comme ailleurs : la fabrique de classeur importe les formes
    définies plus haut, et l'importer au chargement fermerait le cycle.
    """
    from app.services._school_settings_helper import load_school_settings_for_pdf
    from app.services.exports.fee_category_ledger_xlsx import (
        generate_fee_category_ledger_xlsx,
    )

    ledger = await load_category_ledger(
        db,
        category_id=category_id,
        academic_year_id=academic_year_id,
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        received_by=received_by,
        consolide=consolide,
    )
    school = await load_school_settings_for_pdf(db)
    return generate_fee_category_ledger_xlsx(ledger, school)


async def get_category_ledger_pdf(
    db: AsyncSession,
    *,
    category_id: int,
    academic_year_id: int,
    class_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    received_by: int | None = None,
    consolide: bool = True,
) -> bytes:
    """Le même document, au gabarit officiel, en PDF.

    Le classeur sert à recalculer ; le PDF sert à signer et à remettre. Les
    deux lisent le même `CategoryLedger`, chargé une fois : deux compositions
    partant de deux lectures finiraient par annoncer deux totaux, et c'est
    précisément le document qu'on ne peut pas se permettre de voir diverger.
    """
    from app.services._school_settings_helper import load_school_settings_for_pdf
    from app.services.pdf.fee_category_ledger import generate_fee_category_ledger_pdf

    ledger = await load_category_ledger(
        db,
        category_id=category_id,
        academic_year_id=academic_year_id,
        class_id=class_id,
        date_from=date_from,
        date_to=date_to,
        received_by=received_by,
        consolide=consolide,
    )
    school = await load_school_settings_for_pdf(db)
    return generate_fee_category_ledger_pdf(ledger, school)
