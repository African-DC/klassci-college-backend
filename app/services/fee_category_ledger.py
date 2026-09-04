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

## Ce qui est ATTENDU, et le taux qu'on en tire

L'attendu est la somme de ce que les lignes demandent encore en argent : une
ligne exoneree ou deposee en nature n'est plus due, elle sort du total. Le taux
de recouvrement n'est PAS une seconde somme d'allocations : c'est l'attendu
moins ce qui reste du, sur l'attendu — les deux termes sortent des memes lignes
et des memes montants. Une famille qui verse puis se fait exonerer disparait
donc des deux cotes en meme temps, et le taux ne peut pas depasser 100 %.

Le taux suit la ligne de partage : il se lit sur tout l'argent recu, donc il est
ABSENT pour qui ne lit pas toutes les caisses. Calcule sur une seule caisse il
annoncerait une dette chez des familles ayant paye au guichet d'a cote — c'est
la meme faute que le reste du, et elle rentrerait par la porte du pourcentage.
Cette regle vaut aussi pour l'attendu et pour les compteurs par seau : ils
forment un seul bloc, l'outil de recouvrement, et il ne se sert pas a moitie.
La convention du pourcentage est celle du tableau de bord
(`payments/query.py`) : de 0 a 100, une decimale, et `None` plutot qu'un zero
quand il n'est pas calculable.

## Le seau vient du statut de la ligne, jamais du verse affiche

Le tri en seaux — aucun paiement / partiel / a jour — lit `EnrollmentFee.status`
et rien d'autre. Ce statut est recalcule sur **tout** l'argent recu ; le derivant
du `paid` de ce document, on classerait « impaye » une famille qu'une collegue a
soldee. C'est aussi le champ du badge de la ligne : une seule regle pour une
seule question, sans quoi un eleve serait « a jour » dans l'onglet et
« partiel » sur sa ligne.

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

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BusinessValidationError
from app.core.names import compact
from app.models.academic import Class
from app.models.enrollment import CLOSED_STATUSES, Enrollment
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    cash_remaining,
    is_not_cash_due,
)
from app.models.user import Student
from app.services import fees_paid
from app.utils.fuzzy_search import fuzzy_filter_by_name

#: Au-dela, le document cesse de rendre service : personne ne relit cinq mille
#: lignes, et la generation se met a peser sur le serveur pendant les heures de
#: guichet. Meme plafond que le journal des versements
#: (`payment_journal_repository.JOURNAL_MAX_ROWS`), et pour la meme raison.
#:
#: La troncature est ANNONCEE par `CategoryLedger.truncated_from`. Un document
#: ampute qui se tait vaut moins qu'un document absent : on le lit comme complet.
LEDGER_MAX_ROWS = 5000

#: Le pseudo-seau de la liste d'appel : tout ce qui reste du en argent.
SEAU_IMPAYES = "impayes"

#: Les seaux qu'un appelant peut demander, et les statuts qu'ils reunissent.
#:
#: Ils sortent de `EnrollmentFee.status`, jamais du verse affiche — voir la
#: section « Le seau vient du statut de la ligne » en tete de module.
SEAUX: dict[str, tuple[str, ...]] = {
    SEAU_IMPAYES: (
        EnrollmentFeeStatus.PENDING.value,
        EnrollmentFeeStatus.PARTIAL.value,
    ),
    **{statut.value: (statut.value,) for statut in EnrollmentFeeStatus},
}


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

    #: Combien d'inscriptions ouvertes tient le périmètre demandé — l'année,
    #: et la classe s'il y en a une. Ce n'est pas de l'argent : ce chiffre ne
    #: se cloisonne pas, et il est le dénominateur de tout ce qui se rapporte
    #: à un effectif.
    effectif_perimetre: int
    #: Ceux qu'aucune ligne de frais de cette catégorie ne couvre. Ils
    #: n'apparaissent nulle part dans `lignes` — l'application ne leur a
    #: jamais posé le frais — et sans ce compte le document rétrécissait son
    #: propre dénominateur en silence : « tout le monde a payé » se lisait sur
    #: une liste où les élèves non facturés manquaient.
    eleves_sans_ligne: int

    #: Ce qui est entré en argent sur la période — ce qu'on envoie au prestataire.
    eleves_en_argent: int
    total_en_argent: Decimal
    #: Ce qui est entré en nature sur la période — ce qu'on doit retrouver en stock.
    depots_en_nature: int
    #: L'état, pas un événement : jamais borné par la période, et `None` sans
    #: le droit de lire toutes les caisses.
    eleves_restant_du: int | None
    total_restant_du: Decimal | None

    #: Ce que les lignes demandent encore en argent — exonérées et déposées en
    #: nature exclues, puisqu'elles ne sont plus dues. C'est le dénominateur du
    #: taux, et le numérateur en sort par soustraction : les deux décrivent le
    #: même ensemble de lignes, donc le taux ne peut pas dépasser 100 %.
    total_attendu: Decimal | None
    #: De 0 à 100, une décimale — la convention du tableau de bord
    #: (`payments/query.py`). `None` sans le droit de lire toutes les caisses,
    #: et `None` aussi quand rien n'est attendu : un taux sans dénominateur
    #: n'est pas zéro, il n'existe pas.
    taux_recouvrement: float | None
    #: Combien de lignes par état, sur le périmètre entier — jamais sur la
    #: page. Les cinq clés sont toujours présentes, et leur somme vaut le
    #: nombre de lignes du périmètre : un compteur d'onglet qui ne retombe pas
    #: sur la liste fait douter des deux.
    compteurs: dict[str, int] | None

    #: Le seau demandé, et la recherche saisie. Portés par le document parce
    #: qu'une liste filtrée qui ne dit pas son filtre se lit comme complète.
    etat_filtre: str | None
    recherche: str | None
    #: Vrai quand la recherche exacte n'a rien rendu et que la liste vient du
    #: repêchage flou. L'écran doit le dire : une liste de fiches approchantes
    #: servie sans un mot se lit comme la réponse à ce qu'on a tapé, et on
    #: encaisserait sur l'homonyme.
    recherche_approchee: bool
    #: Combien de lignes le filtre retient sur le périmètre, avant pagination.
    total_lignes: int
    page: int
    size: int
    #: Rempli quand le plafond a coupé : le nombre de lignes que le filtre
    #: retenait réellement. `None` quand rien n'a été amputé — tourner une
    #: page n'est pas une troncature.
    truncated_from: int | None

    lignes: tuple[LigneEleve, ...]


def _seau_demande(state: str | None, *, consolide: bool) -> tuple[str, ...] | None:
    """Les statuts que le seau demandé réunit, ou `None` s'il n'y a pas de filtre.

    Deux refus explicites, tous deux préférables à une liste vide : une liste
    vide se lirait « personne ne doit rien », et c'est le contraire de ce qui
    s'est passé.

    Le second refus est la ligne de partage appliquée jusqu'au bout. Le tri en
    seaux est l'outil de recouvrement, au même titre que l'attendu, le taux et
    le reste dû ; le recouvrement se lit sur tout l'argent reçu. Sans le droit
    de lire toutes les caisses, il n'est pas servi — ni entier, ni approché.
    Ce que la caissière garde est son propre encaissement, qui est un fait sur
    sa caisse : le total entré, ses dépôts, et l'effectif qu'elle devait couvrir.
    """
    if state is None:
        return None
    if not consolide:
        raise BusinessValidationError(
            "Le tri par état se lit sur tout l'argent reçu, toutes caisses "
            "confondues : sur une seule caisse, il classerait « impayée » une "
            "famille qui a payé au guichet d'à côté. Votre point porte ce que "
            "vous avez encaissé."
        )
    statuts = SEAUX.get(state)
    if statuts is None:
        raise BusinessValidationError(
            f"État inconnu : « {state} ». Attendu : {', '.join(sorted(SEAUX))}."
        )
    return statuts


def _echappe(mot: str) -> str:
    """Neutralise les jokers d'un `LIKE` saisis au clavier.

    Un « % » tapé dans la barre de recherche est un caractère, pas « tout ».
    """
    return mot.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions_de_recherche(q: str | None) -> list[object]:
    """La recherche par nom, prénom ou matricule, mot à mot.

    Sur les colonnes normalisées que l'élève porte déjà — `last_name_key` et
    `first_name_key`, maintenues à l'écriture par le modèle — et non sur le nom
    brut : « KOUAMÉ » doit se trouver en tapant « kouame », et « N'DRI » en
    tapant « ndri ». La règle de repliage vit dans `app.core.names.compact`, à
    un seul endroit ; en écrire une seconde ici est précisément ce que ce
    module-là raconte avoir coûté — une fiche enregistrée avec « œ » restait
    introuvable parce que les deux exemplaires avaient divergé.

    Chaque mot doit correspondre, sur l'un des trois champs : « KOUAME Aya » ne
    doit pas remonter tous les KOUAME. Le matricule se compare sur la colonne
    nue, dont la collation est déjà insensible à la casse ; l'envelopper dans
    un `lower()` interdirait à la base d'utiliser son index unique.

    C'est la recherche EXACTE. Quand elle ne rend rien, `load_category_ledger`
    repasse en flou — voir le repêchage, plus bas.
    """
    conditions: list[object] = []
    for mot in (q or "").split():
        alternatives: list[object] = []
        cle = compact(mot)
        if cle:
            # `compact` ne laisse que des caractères alphanumériques : il n'y a
            # aucun joker à échapper dans ce motif-ci.
            alternatives.append(Student.last_name_key.like(f"%{cle}%"))
            alternatives.append(Student.first_name_key.like(f"%{cle}%"))
        alternatives.append(Student.enrollment_number.like(f"%{_echappe(mot)}%", escape="\\"))
        conditions.append(or_(*alternatives))
    return conditions


def _lignes_stmt(conditions: list[object]):
    """La requête des lignes affichables, relations chargées.

    Une seule écriture pour les deux chemins — la liste ordonnée et le
    repêchage flou : ils doivent rendre les mêmes objets, sans quoi une
    colonne se remplirait sur l'un et pas sur l'autre.

    Le chargement des relations est explicite : sans lui, chaque ligne
    déclencherait sa requête au moment du rendu, hors contexte asynchrone.
    """
    return (
        select(EnrollmentFee)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .join(Student, Student.id == Enrollment.student_id)
        .where(*conditions)
        .options(
            selectinload(EnrollmentFee.enrollment).selectinload(Enrollment.student),
            selectinload(EnrollmentFee.enrollment).selectinload(Enrollment.class_),
        )
    )


def _nom_cherchable(ligne: EnrollmentFee) -> str:
    """Ce sur quoi le repêchage flou compare : le nom vu par la personne qui tape."""
    eleve = ligne.enrollment.student
    return f"{eleve.first_name} {eleve.last_name} {eleve.enrollment_number or ''}"


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
    state: str | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = LEDGER_MAX_ROWS,
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

    `state`, `q`, `page` et `size` ne bornent QUE la liste. Les totaux et les
    compteurs se calculent sur le périmètre entier — sinon le chiffre du haut
    de page descendrait à chaque page tournée, et l'onglet « Aucun paiement »
    n'annoncerait plus que ce qu'on a déjà chargé. C'est la seule façon que le
    document exporté retombe sur l'écran.

    La liste est plafonnée à `LEDGER_MAX_ROWS`, et `truncated_from` le dit
    quand la coupe a eu lieu.
    """
    statuts_du_seau = _seau_demande(state, consolide=consolide)
    recherche = (q or "").strip() or None
    conditions_de_recherche = _conditions_de_recherche(recherche)
    # Bornes défensives : le routeur les pose déjà, mais ce service se lit
    # aussi depuis les deux fabriques de documents, qui n'ont pas de validateur
    # au-dessus d'elles.
    page = max(page, 1)
    size = min(max(size, 1), LEDGER_MAX_ROWS)

    categorie = (
        await db.execute(select(FeeCategory).where(FeeCategory.id == category_id))
    ).scalar_one_or_none()

    inscriptions_conditions = [
        Enrollment.academic_year_id == academic_year_id,
        Enrollment.status.not_in(CLOSED_STATUSES),
    ]
    if class_id is not None:
        inscriptions_conditions.append(Enrollment.class_id == class_id)

    perimetre_conditions = [
        EnrollmentFee.fee_category_id == category_id,
        *inscriptions_conditions,
    ]

    # LE PERIMETRE ENTIER, en colonnes nues : c'est lui qui porte les totaux et
    # les compteurs. Jamais la page — un compteur d'onglet tire de la page
    # baisserait a chaque page tournee, et le document exporte ne retomberait
    # plus sur l'ecran. Sans les noms ni les relations : ce qu'on additionne
    # ici, ce sont des montants et des statuts.
    perimetre = (
        await db.execute(
            select(
                EnrollmentFee.id,
                EnrollmentFee.amount,
                EnrollmentFee.status,
                EnrollmentFee.deposited_at,
                EnrollmentFee.deposited_by_user_id,
            )
            .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
            .where(*perimetre_conditions)
        )
    ).all()

    fee_ids = [int(row.id) for row in perimetre]
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

    # L'effectif du perimetre et les eleves qu'aucune ligne ne couvre. Les deux
    # se lisent sur le PERIMETRE, jamais sur `lignes` : la liste rendue est
    # filtree et paginee, et un denominateur tire d'elle baisserait a chaque
    # page tournee. `perimetre` est bien le perimetre entier ; c'est la seconde
    # requete, plus bas, qui porte le filtre et la page.
    #
    # Ce sont des inscriptions, pas de l'argent : ils ne se cloisonnent donc
    # pas. Une caissiere a le droit de savoir combien d'eleves son document
    # aurait du couvrir.
    effectif = int(
        (
            await db.execute(
                select(func.count()).select_from(Enrollment).where(*inscriptions_conditions)
            )
        ).scalar_one()
        or 0
    )
    # `uq_enrollment_fee_category` garantit une ligne par inscription et par
    # categorie : compter les lignes du perimetre, c'est compter les eleves
    # qu'elles couvrent.
    sans_ligne = max(effectif - len(perimetre), 0)

    eleves_en_argent = 0
    total_en_argent = Decimal("0")
    depots = 0
    eleves_du = 0
    total_du = Decimal("0")
    total_attendu = Decimal("0")
    compteurs = {statut.value: 0 for statut in EnrollmentFeeStatus}

    for row in perimetre:
        statut = str(getattr(row.status, "value", row.status))
        montant = Decimal(str(row.amount or 0))
        paye = verse.get(int(row.id), Decimal("0"))

        # Le seau sort du statut, jamais du verse : ce statut-la est recalcule
        # sur tout l'argent recu, et c'est aussi celui du badge de la ligne.
        if statut in compteurs:
            compteurs[statut] += 1

        if paye > 0:
            eleves_en_argent += 1
            total_en_argent += paye

        # Un depot est quelque chose qui est ENTRE : il se cloisonne donc comme
        # l'argent. `received_by` ne filtrait que les versements, et ce compte
        # rendait a une caissiere le total de toute l'ecole sous un document
        # qui affirme en toutes lettres ne couvrir que sa caisse.
        depose = statut == EnrollmentFeeStatus.IN_KIND.value
        de_ma_main = received_by is None or row.deposited_by_user_id == received_by
        if depose and de_ma_main and _dans_la_fenetre(row.deposited_at, date_from, date_to):
            depots += 1

        # L'ATTENDU : ce que les lignes demandent ENCORE en argent. Une ligne
        # exoneree ou deposee en nature n'est plus due : elle sort du
        # denominateur — et, parce que le numerateur est ce meme montant moins
        # le reste du, elle sort du numerateur avec lui. Une famille qui verse
        # puis se fait exonerer ne peut donc pas rester au numerateur seule et
        # pousser le taux au-dela de 100 %.
        if not is_not_cash_due(statut):
            total_attendu += montant

        if consolide:
            # Sur tout l'argent recu, jamais sur la fenetre : une famille qui a
            # paye le mois dernier ne doit rien ce mois-ci.
            reste = cash_remaining(statut, montant, verse_total.get(int(row.id), Decimal("0")))
            if reste > 0:
                eleves_du += 1
                total_du += reste

    # LE TAUX : le recouvre sur l'attendu, et le recouvre n'est pas une seconde
    # somme d'allocations — c'est l'attendu moins ce qui reste du. `cash_remaining`
    # bornant deja chaque ligne a son propre montant, un trop-percu ne peut pas
    # faire deborder le total. Absent, jamais approche, quand on ne lit pas
    # toutes les caisses ; absent aussi quand rien n'est attendu, parce qu'un
    # taux sans denominateur n'est pas zero.
    taux: float | None = None
    if consolide and total_attendu > 0:
        taux = round(float((total_attendu - total_du) / total_attendu * 100), 1)

    # LA LISTE : le seul endroit ou le seau, la recherche et la page portent.
    liste_conditions = [*perimetre_conditions]
    if statuts_du_seau is not None:
        liste_conditions.append(EnrollmentFee.status.in_(statuts_du_seau))
    liste_conditions.extend(conditions_de_recherche)

    if statuts_du_seau is None and not conditions_de_recherche:
        # Sans filtre de liste, la liste EST le perimetre : le recompter serait
        # poser deux fois la meme question a la base.
        total_lignes = len(perimetre)
    else:
        total_lignes = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(EnrollmentFee)
                    .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
                    .join(Student, Student.id == Enrollment.student_id)
                    .where(*liste_conditions)
                )
            ).scalar_one()
            or 0
        )

    depart = (page - 1) * size
    # Le plafond borne la LISTE entiere, pas chaque page : passe la
    # cinq-millieme ligne, il n'y a plus rien a servir, et `truncated_from` le
    # dit au lieu de laisser croire a une fin de liste.
    fenetre = min(size, max(LEDGER_MAX_ROWS - depart, 0))
    frais: list[EnrollmentFee] = []
    if fenetre > 0:
        stmt = (
            _lignes_stmt(liste_conditions)
            .order_by(Student.last_name, Student.first_name, EnrollmentFee.id)
            .offset(depart)
            .limit(fenetre)
        )
        frais = list((await db.execute(stmt)).scalars().all())

    # LE REPECHAGE : la recherche exacte n'a rien rendu, on retente en flou.
    # Meme geste que la liste des eleves (`admin_repository.list_students`),
    # meme raison : « KOUASI » tape pour « KOUASSI » ne doit pas rendre une
    # page vide qu'on lirait comme « cet eleve n'est pas dans cette classe ».
    # Le seau reste applique — on cherche dans l'onglet ouvert, pas a cote —
    # et l'ordre devient celui de la pertinence, puisqu'il n'y a plus d'ordre
    # alphabetique a tenir sur un ensemble vide.
    approchee = False
    if recherche and total_lignes == 0 and depart == 0:
        candidats_conditions = [*perimetre_conditions]
        if statuts_du_seau is not None:
            candidats_conditions.append(EnrollmentFee.status.in_(statuts_du_seau))
        candidats = list((await db.execute(_lignes_stmt(candidats_conditions))).scalars().all())
        frais = fuzzy_filter_by_name(
            candidats,
            recherche,
            name_getter=_nom_cherchable,
            limit=size,
        )
        total_lignes = len(frais)
        # Le dire, et ne pas laisser l'ecran servir des fiches approchantes
        # comme si c'etait la reponse a ce qu'on a tape : on encaisserait sur
        # l'homonyme.
        approchee = bool(frais)

    lignes: list[LigneEleve] = []
    for ligne in frais:
        inscription = ligne.enrollment
        eleve = inscription.student
        statut = str(getattr(ligne.status, "value", ligne.status))
        montant = Decimal(str(ligne.amount or 0))
        reste: Decimal | None = None
        if consolide:
            reste = cash_remaining(statut, montant, verse_total.get(ligne.id, Decimal("0")))

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
                paid=verse.get(ligne.id, Decimal("0")),
                remaining=reste,
                deposited_at=ligne.deposited_at,
            )
        )

    return CategoryLedger(
        category_id=category_id,
        category_name=getattr(categorie, "name", "") or f"Catégorie {category_id}",
        accepts_in_kind=bool(getattr(categorie, "accepts_in_kind", False)),
        class_name=await _nom_du_perimetre(db, class_id),
        date_from=date_from,
        date_to=date_to,
        consolide=consolide,
        effectif_perimetre=effectif,
        eleves_sans_ligne=sans_ligne,
        eleves_en_argent=eleves_en_argent,
        total_en_argent=total_en_argent,
        depots_en_nature=depots,
        eleves_restant_du=eleves_du if consolide else None,
        total_restant_du=total_du if consolide else None,
        total_attendu=total_attendu if consolide else None,
        taux_recouvrement=taux,
        compteurs=compteurs if consolide else None,
        etat_filtre=state,
        recherche=recherche,
        recherche_approchee=approchee,
        total_lignes=total_lignes,
        page=page,
        size=size,
        truncated_from=total_lignes if total_lignes > LEDGER_MAX_ROWS else None,
        lignes=tuple(lignes),
    )


async def _nom_du_perimetre(db: AsyncSession, class_id: int | None) -> str:
    """Le nom du périmètre, lu depuis le CRITÈRE et non depuis les lignes.

    Le reconstituer à partir de la première ligne rendue marchait tant que la
    liste couvrait tout le périmètre. Filtrée sur un seau ou sur une recherche,
    elle peut être vide alors que la classe existe et compte des élèves : le
    document perdait alors le nom de ce qu'il montre, au moment précis où il
    en avait le plus besoin.
    """
    if class_id is None:
        return "Toutes les classes"
    nom = (await db.execute(select(Class.name).where(Class.id == class_id))).scalar_one_or_none()
    return nom or ""


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

    Le seau et la recherche de l'écran ne sont volontairement pas transmis : le
    document porte le périmètre entier, plafond compris. Un classeur amputé
    d'un filtre qu'il ne nomme pas se lirait comme le point complet, et c'est
    la pièce qu'un prestataire garde. Les y ajouter suppose que l'en-tête
    nomme d'abord ses filtres.
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

    Comme le classeur, il porte le périmètre entier et non le filtre de liste
    de l'écran : un PDF filtré qui ne dit pas son filtre est un faux point.
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
