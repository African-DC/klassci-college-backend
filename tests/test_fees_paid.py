"""Ce qu'une famille a versé — mesuré en interrogeant une vraie base.

Le bug que ces tests existent pour empêcher : depuis la migration 0028, un
versement se fait sur l'INSCRIPTION et se répartit sur les frais par des lignes
`PaymentAllocation`. La colonne `Payment.enrollment_fee_id` et la relation
`EnrollmentFee.payments` qui s'appuie dessus ne sont plus renseignées. Tout
code qui les somme encore rend zéro sous un frais pourtant soldé — et sur les
portails, c'est la famille elle-même qui lit ce chiffre.

C'est exactement la forme que prend la fixture : le versement n'existe QUE par
son allocation, `enrollment_fee_id` reste vide. Un calcul qui relirait
l'ancienne relation rendrait zéro, et chacun de ces tests le dirait.

Une version antérieure de ce fichier ne vérifiait rien de tout cela : elle
parcourait l'arbre syntaxique des modules applicatifs pour s'assurer qu'un nom
d'attribut n'y apparaissait pas. Un test qui lit le texte du programme fige une
écriture au lieu de garder un comportement — sur ce projet, un test de ce genre
a verrouillé pendant des semaines un bug qui faisait sortir un document
officiel faux. La contrepartie est assumée : le filet couvre désormais les
fonctions canoniques et l'écran qui les consomme, au lieu du dépôt entier. Il
est plus étroit, mais il détecte un mauvais montant plutôt qu'une mauvaise
orthographe.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
)
from app.models.user import Student
from app.services import fee_situation, fees_paid

ELEVE = 1
INSCRIPTION = 10
INSCRIPTION_ANNEE_PRECEDENTE = 11

FRAIS_INSCRIPTION = 100
FRAIS_T1 = 101
FRAIS_TENUE = 102
FRAIS_EXONERE = 103
FRAIS_ANNEE_PRECEDENTE = 104

VERSEMENT_REPARTI = 500
VERSEMENT_EN_ATTENTE = 501
VERSEMENT_ANNEE_PRECEDENTE = 502


class _Pont:
    """Donne l'allure d'une `AsyncSession` a une session synchrone.

    Les fonctions mesurees n'utilisent que `execute`. L'envelopper evite
    d'ajouter un pilote asynchrone pour faire tourner des tests.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _categorie(ident: int, nom: str, priorite: int, *, obligatoire: bool) -> FeeCategory:
    return FeeCategory(id=ident, name=nom, priority=priorite, is_mandatory=obligatoire)


def _frais(
    ident: int,
    inscription: int,
    variante: int,
    categorie: int,
    montant: str,
    statut: str = EnrollmentFeeStatus.PENDING.value,
) -> EnrollmentFee:
    return EnrollmentFee(
        id=ident,
        enrollment_id=inscription,
        fee_variant_id=variante,
        fee_category_id=categorie,
        amount=Decimal(montant),
        status=statut,
    )


def _versement(ident: int, inscription: int, montant: str, statut: str) -> Payment:
    """Un versement tel que la caisse le produit depuis 0028.

    `enrollment_fee_id` reste vide : c'est tout l'objet de ce fichier. Le lien
    vers les frais ne passe que par les allocations.
    """
    return Payment(
        id=ident,
        enrollment_id=inscription,
        amount=Decimal(montant),
        method=PaymentMethod.CASH.value,
        status=statut,
        enrollment_fee_id=None,
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    """Une inscription, quatre frais, et des versements qui n'existent que par
    leurs allocations."""
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=1,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                AcademicYear(
                    id=2,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=False,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                Student(id=ELEVE, last_name="KOUASSI", first_name="Aya"),
                Enrollment(id=INSCRIPTION, student_id=ELEVE, class_id=1, academic_year_id=1),
                Enrollment(
                    id=INSCRIPTION_ANNEE_PRECEDENTE,
                    student_id=ELEVE,
                    class_id=1,
                    academic_year_id=2,
                ),
                # Priorites croissantes : c'est l'ordre du tableau affiche.
                _categorie(1, "Inscription", 1, obligatoire=True),
                _categorie(2, "Scolarite T1", 2, obligatoire=True),
                _categorie(4, "Scolarite T2", 3, obligatoire=True),
                # La tenue est facultative : elle sort du calcul des frais dus.
                _categorie(3, "Tenue", 6, obligatoire=False),
                FeeVariant(id=1, fee_category_id=1, academic_year_id=1, amount=Decimal("25000")),
                FeeVariant(id=2, fee_category_id=2, academic_year_id=1, amount=Decimal("50000")),
                FeeVariant(id=3, fee_category_id=3, academic_year_id=1, amount=Decimal("15000")),
                FeeVariant(id=4, fee_category_id=1, academic_year_id=2, amount=Decimal("20000")),
                FeeVariant(id=5, fee_category_id=4, academic_year_id=1, amount=Decimal("50000")),
                _frais(FRAIS_INSCRIPTION, INSCRIPTION, 1, 1, "25000"),
                _frais(FRAIS_T1, INSCRIPTION, 2, 2, "50000"),
                _frais(FRAIS_TENUE, INSCRIPTION, 3, 3, "15000"),
                # Exonere apres avoir recu de l'argent : le cas qui faisait
                # apparaitre une famille en avance sur une scolarite impayee.
                _frais(
                    FRAIS_EXONERE,
                    INSCRIPTION,
                    5,
                    4,
                    "50000",
                    statut=EnrollmentFeeStatus.WAIVED.value,
                ),
                _frais(FRAIS_ANNEE_PRECEDENTE, INSCRIPTION_ANNEE_PRECEDENTE, 4, 1, "20000"),
            ]
        )
        s.flush()

        s.add_all(
            [
                _versement(VERSEMENT_REPARTI, INSCRIPTION, "50000", PaymentStatus.COMPLETED.value),
                _versement(VERSEMENT_EN_ATTENTE, INSCRIPTION, "15000", PaymentStatus.PENDING.value),
                _versement(
                    VERSEMENT_ANNEE_PRECEDENTE,
                    INSCRIPTION_ANNEE_PRECEDENTE,
                    "20000",
                    PaymentStatus.COMPLETED.value,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                # Un versement de 50 000 reparti sur trois frais.
                PaymentAllocation(
                    payment_id=VERSEMENT_REPARTI,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("25000"),
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT_REPARTI,
                    enrollment_fee_id=FRAIS_T1,
                    amount=Decimal("20000"),
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT_REPARTI,
                    enrollment_fee_id=FRAIS_EXONERE,
                    amount=Decimal("5000"),
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT_EN_ATTENTE,
                    enrollment_fee_id=FRAIS_TENUE,
                    amount=Decimal("15000"),
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT_ANNEE_PRECEDENTE,
                    enrollment_fee_id=FRAIS_ANNEE_PRECEDENTE,
                    amount=Decimal("20000"),
                ),
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_un_versement_alloue_compte_comme_paye(db: Session) -> None:
    """Le bug fondateur, pris par le montant.

    Un frais soldé par une allocation doit apparaître payé. Un calcul qui
    relirait `EnrollmentFee.payments` rendrait un dictionnaire vide, donc zéro
    partout, et la famille verrait sa dette intacte après avoir payé.
    """
    verse = await fees_paid.paid_by_enrollment_fee(_Pont(db), ELEVE)
    assert verse[FRAIS_INSCRIPTION] == Decimal("25000")
    assert verse[FRAIS_T1] == Decimal("20000")


@pytest.mark.asyncio
async def test_le_verse_est_borne_a_l_inscription_demandee(db: Session) -> None:
    """Un élève qui a redoublé a deux inscriptions.

    Mélanger leurs versements ferait apparaître comme soldée une année qui ne
    l'est pas — et l'établissement délivre des documents sur ce chiffre.
    """
    annee_courante = await fees_paid.paid_by_enrollment(_Pont(db), INSCRIPTION)
    assert FRAIS_ANNEE_PRECEDENTE not in annee_courante

    annee_passee = await fees_paid.paid_by_enrollment(_Pont(db), INSCRIPTION_ANNEE_PRECEDENTE)
    assert annee_passee == {FRAIS_ANNEE_PRECEDENTE: Decimal("20000")}


@pytest.mark.asyncio
async def test_un_versement_non_encaisse_ne_compte_pas_comme_paye(db: Session) -> None:
    """Tant que l'argent n'est pas encaissé, il n'est pas versé.

    Le compter avancerait la famille sur un virement qui peut encore échouer.
    """
    verse = await fees_paid.paid_by_enrollment(_Pont(db), INSCRIPTION)
    assert FRAIS_TENUE not in verse, "un versement en attente ne solde rien"


@pytest.mark.asyncio
async def test_un_frais_portant_une_ecriture_est_protege_meme_non_encaissee(db: Session) -> None:
    """L'autre question, et volontairement l'inverse de la précédente.

    Ici on ne demande pas combien la famille a versé, mais si ce frais porte
    une écriture. Un versement en attente a déjà sa ligne d'allocation :
    détruire le frais dessous ferait perdre sa contrepartie à un encaissement
    que la caisse a enregistré.
    """
    proteges = await fees_paid.fee_ids_with_allocations(_Pont(db), INSCRIPTION)
    assert FRAIS_TENUE in proteges, "le frais en attente doit rester protégé"
    assert FRAIS_INSCRIPTION in proteges


@pytest.mark.asyncio
async def test_le_detail_montre_la_part_du_versement_pas_son_total(db: Session) -> None:
    """Un versement de 50 000 réparti sur trois frais.

    Sous le premier, il doit apparaître pour 25 000 — sa part — et non pour
    50 000, sinon la liste affichée ne se recoupe plus avec le total et la
    famille voit trois fois son argent.
    """
    detail = await fees_paid.payments_by_enrollment_fee(_Pont(db), INSCRIPTION)
    versement, part = detail[FRAIS_INSCRIPTION][0]
    assert versement.id == VERSEMENT_REPARTI
    assert versement.amount == Decimal("50000"), "le versement entier vaut bien 50 000"
    assert part == Decimal("25000"), "mais seule sa part revient à ce frais"


@pytest.mark.asyncio
async def test_l_argent_pose_sur_un_frais_exonere_sort_du_calcul(db: Session) -> None:
    """Le cas qui mettait une famille en avance sur une scolarité impayée.

    Une famille verse, l'école lui accorde ensuite une bourse et exonère le
    frais. L'attendu baisse ; si le versé ne bougeait pas, la famille
    apparaîtrait en avance et l'échéancier cesserait de la signaler en retard —
    or c'est lui qui commande la retenue des documents administratifs.

    Le facultatif sort aussi : 15 000 de tenue ne soldent pas une scolarité.
    """
    sur_frais_dus = await fees_paid.paid_on_mandatory(_Pont(db), INSCRIPTION)
    assert sur_frais_dus == Decimal("45000"), (
        "25 000 d'inscription + 20 000 de T1 ; ni les 5 000 posés sur le frais "
        "exonéré, ni la tenue facultative"
    )


@pytest.mark.asyncio
async def test_le_total_de_l_annee_suit_le_meme_perimetre(db: Session) -> None:
    """Le chiffre du tableau de bord doit se recouper avec les fiches.

    S'il totalisait les versements bruts pendant que la fiche de chaque élève
    en exclut les exonérés, le taux d'avancement de l'école contredirait la
    somme de ses élèves.
    """
    annee_courante = await fees_paid.paid_on_mandatory_for_year(_Pont(db), 1)
    assert annee_courante == Decimal("45000")

    toutes_annees = await fees_paid.paid_on_mandatory_for_year(_Pont(db), None)
    assert toutes_annees == Decimal("65000"), "45 000 cette année, 20 000 la précédente"


@pytest.mark.asyncio
async def test_le_tableau_lu_par_la_famille_montre_l_argent_recu(db: Session) -> None:
    """Le bout de la chaîne : l'écran, pas la fonction.

    C'est ici que le bug se voyait — un frais soldé, aucun versement en
    dessous, et une famille qui pouvait croire son argent perdu. Le test
    traverse tout le calcul jusqu'au tableau affiché.
    """
    situation = await fee_situation.load_situation(_Pont(db), INSCRIPTION)

    par_categorie = {ligne.category_name: ligne for ligne in situation.lines}
    assert par_categorie["Inscription"].paid == Decimal("25000")
    assert par_categorie["Inscription"].remaining == Decimal("0")

    scolarite = [ligne for ligne in situation.lines if ligne.category_name == "Scolarite T1"]
    assert any(ligne.paid == Decimal("20000") for ligne in scolarite)

    assert situation.total_paid == Decimal("50000"), (
        "les trois allocations du versement encaissé, exonéré compris : c'est "
        "de l'argent reçu, il doit se voir"
    )
    assert situation.total_paid > 0, "un tableau à zéro est le symptôme du bug d'origine"
