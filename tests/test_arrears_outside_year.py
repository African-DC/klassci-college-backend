"""Ce qu'un élève doit sur les AUTRES exercices — mesuré sur une vraie base.

L'angle mort que ces tests gardent : quarante-trois élèves devaient
2 257 000 F sur l'exercice précédent sans être encore réinscrits. Le jour de
leur réinscription, les portails et la fiche élève — qui lisent tous
l'inscription la plus récente — auraient basculé sur la nouvelle année, et
cette dette serait sortie de tous les écrans à la fois. Aucun chiffre n'était
faux : plus personne ne regardait celui-là.

Les tests somment donc en base, sur des inscriptions réparties sur deux
exercices, plutôt que de vérifier la forme du code. Un montant faux doit faire
tomber ce fichier ; une réécriture propre, non.
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
from app.models.enrollment import Enrollment, EnrollmentStatus
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
from app.services import fees_paid
from app.services.finance_visibility import FinanceView

ANNEE_COURANTE = 1
ANNEE_PRECEDENTE = 2

ENDETTE = 1
NON_REINSCRIT = 2
EXONERE = 3
VERSEMENT_ANNULE = 4
DOSSIER_CLOS = 5
FRAIS_FACULTATIF = 6
TROP_PERCU = 7


class _Pont:
    """Donne l'allure d'une `AsyncSession` à une session synchrone.

    Les fonctions mesurées n'utilisent que `execute`. L'envelopper évite
    d'ajouter un pilote asynchrone pour faire tourner des tests.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _inscription(
    ident: int,
    eleve: int,
    annee: int,
    statut: str = EnrollmentStatus.VALIDE.value,
) -> Enrollment:
    return Enrollment(id=ident, student_id=eleve, class_id=1, academic_year_id=annee, status=statut)


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
    """Un versement tel que la caisse le produit depuis la migration 0028.

    `enrollment_fee_id` reste vide : le lien vers les frais ne passe que par
    les allocations, et c'est par elles que le versé se lit.
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
    """Sept élèves, chacun portant un cas que la somme doit trancher."""
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE_COURANTE,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                AcademicYear(
                    id=ANNEE_PRECEDENTE,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=False,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                FeeCategory(id=1, name="Scolarite", priority=1, is_mandatory=True),
                FeeCategory(id=2, name="Tenue", priority=6, is_mandatory=False),
                FeeVariant(
                    id=1, fee_category_id=1, academic_year_id=ANNEE_COURANTE, amount=Decimal("0")
                ),
                FeeVariant(
                    id=2, fee_category_id=1, academic_year_id=ANNEE_PRECEDENTE, amount=Decimal("0")
                ),
                FeeVariant(
                    id=3, fee_category_id=2, academic_year_id=ANNEE_PRECEDENTE, amount=Decimal("0")
                ),
            ]
        )
        s.add_all(
            [
                Student(id=ENDETTE, last_name="KOUASSI", first_name="Aya"),
                Student(id=NON_REINSCRIT, last_name="TRAORE", first_name="Ibrahim"),
                Student(id=EXONERE, last_name="YAO", first_name="Adjoua"),
                Student(id=VERSEMENT_ANNULE, last_name="KONE", first_name="Mariam"),
                Student(id=DOSSIER_CLOS, last_name="BAMBA", first_name="Sekou"),
                Student(id=FRAIS_FACULTATIF, last_name="DIABATE", first_name="Fanta"),
                Student(id=TROP_PERCU, last_name="GNAGNE", first_name="Serge"),
            ]
        )
        s.flush()

        s.add_all(
            [
                # Déjà réinscrit : sa dette de 2025-2026 vient de sortir des écrans.
                _inscription(10, ENDETTE, ANNEE_PRECEDENTE),
                _inscription(20, ENDETTE, ANNEE_COURANTE),
                # Pas encore réinscrit : aucune année en cours à retirer.
                _inscription(11, NON_REINSCRIT, ANNEE_PRECEDENTE),
                _inscription(12, EXONERE, ANNEE_PRECEDENTE),
                _inscription(22, EXONERE, ANNEE_COURANTE),
                _inscription(13, VERSEMENT_ANNULE, ANNEE_PRECEDENTE),
                _inscription(23, VERSEMENT_ANNULE, ANNEE_COURANTE),
                # Dossier fermé : l'école a annulé, la dette est close avec lui.
                _inscription(14, DOSSIER_CLOS, ANNEE_PRECEDENTE, EnrollmentStatus.ANNULE.value),
                _inscription(24, DOSSIER_CLOS, ANNEE_COURANTE),
                _inscription(15, FRAIS_FACULTATIF, ANNEE_PRECEDENTE),
                _inscription(25, FRAIS_FACULTATIF, ANNEE_COURANTE),
                _inscription(16, TROP_PERCU, ANNEE_PRECEDENTE),
                _inscription(26, TROP_PERCU, ANNEE_COURANTE),
            ]
        )
        s.flush()

        s.add_all(
            [
                _frais(200, 10, 2, 1, "100000"),
                _frais(210, 20, 1, 1, "150000"),
                _frais(201, 11, 2, 1, "80000"),
                _frais(202, 12, 2, 1, "90000", statut=EnrollmentFeeStatus.WAIVED.value),
                _frais(212, 22, 1, 1, "150000"),
                _frais(203, 13, 2, 1, "50000"),
                _frais(213, 23, 1, 1, "150000"),
                _frais(204, 14, 2, 1, "70000"),
                _frais(214, 24, 1, 1, "150000"),
                _frais(205, 15, 3, 2, "15000"),
                _frais(215, 25, 1, 1, "150000"),
                # Une seule ligne par categorie et par inscription : la
                # seconde est donc la tenue, impayee a cote d'une scolarite
                # trop payee.
                _frais(206, 16, 2, 1, "50000"),
                _frais(207, 16, 3, 2, "50000"),
                _frais(216, 26, 1, 1, "150000"),
            ]
        )
        s.flush()

        s.add_all(
            [
                _versement(900, 10, "40000", PaymentStatus.COMPLETED.value),
                _versement(901, 13, "50000", PaymentStatus.CANCELLED.value),
                _versement(902, 16, "80000", PaymentStatus.COMPLETED.value),
            ]
        )
        s.flush()

        s.add_all(
            [
                PaymentAllocation(payment_id=900, enrollment_fee_id=200, amount=Decimal("40000")),
                PaymentAllocation(payment_id=901, enrollment_fee_id=203, amount=Decimal("50000")),
                PaymentAllocation(payment_id=902, enrollment_fee_id=206, amount=Decimal("80000")),
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_la_dette_de_l_annee_precedente_survit_a_la_reinscription(db: Session) -> None:
    """Le cas mesuré en production, pris par le montant.

    Cet élève doit 60 000 sur 2025-2026 et vient d'être réinscrit en
    2026-2027. Tous les écrans lisent désormais la nouvelle inscription : sans
    cette somme, sa dette n'existe plus nulle part.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=ENDETTE, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("60000"), "100 000 dus l'an dernier, 40 000 encaissés"


@pytest.mark.asyncio
async def test_l_annee_affichee_est_retiree_et_pas_une_autre(db: Session) -> None:
    """Le chiffre s'ajoute à ce que l'écran montre : il ne doit pas le recompter.

    Depuis l'année en cours on ne voit que l'ancienne dette ; depuis
    l'ancienne, que la nouvelle. Un retrait portant sur la mauvaise année
    afficherait deux fois le même argent.
    """
    depuis_l_annee_passee = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=ENDETTE, academic_year_id=ANNEE_PRECEDENTE
    )
    assert depuis_l_annee_passee == Decimal("150000"), "la scolarité de l'année en cours, seule"


@pytest.mark.asyncio
async def test_un_eleve_pas_encore_reinscrit_doit_tout_ailleurs(db: Session) -> None:
    """Aucune inscription en cours : il n'y a aucune année à retirer.

    C'est l'état des quarante-trois élèves au moment de la mesure. Le portail
    de leur famille n'a pas d'inscription courante à afficher, et sans ce
    total il ne leur dit plus rien du tout.
    """
    sans_annee = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=NON_REINSCRIT, academic_year_id=None
    )
    assert sans_annee == Decimal("80000")

    hors_annee_courante = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=NON_REINSCRIT, academic_year_id=ANNEE_COURANTE
    )
    assert hors_annee_courante == Decimal("80000"), (
        "retirer une année où il n'a rien ne change rien"
    )


@pytest.mark.asyncio
async def test_une_ligne_exoneree_n_est_plus_due(db: Session) -> None:
    """Une bourse efface la dette, elle ne la reporte pas.

    La compter réclamerait 90 000 à une famille que l'école a exonérée, et
    l'écran de réinscription lui opposerait un impayé inventé.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=EXONERE, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("0")


@pytest.mark.asyncio
async def test_un_versement_annule_ne_solde_rien(db: Session) -> None:
    """L'argent rendu n'est plus de l'argent reçu.

    L'allocation reste en base après l'annulation ; c'est le statut du
    versement qui tranche. Une somme écrite sans ce filtre ressusciterait un
    encaissement annulé et ferait disparaître la dette.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=VERSEMENT_ANNULE, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("50000"), "le versement annulé ne solde rien"


@pytest.mark.asyncio
async def test_un_dossier_clos_ne_doit_plus_rien(db: Session) -> None:
    """Une inscription annulée ferme sa dette avec elle.

    La relancer ferait réapparaître un impayé sur un dossier que
    l'établissement a fermé — c'est la règle que `CLOSED_STATUSES` porte déjà.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=DOSSIER_CLOS, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("0")


@pytest.mark.asyncio
async def test_un_frais_facultatif_impaye_reste_de_l_argent_du(db: Session) -> None:
    """Une tenue impayée est de l'argent que la famille doit à l'école.

    Le périmètre « frais obligatoires » est celui de l'échéancier, qui répond
    à une autre question. Ici c'est le même périmètre que le `total_due`
    affiché juste au-dessus sur le portail : en retenir un autre ferait un
    écran qui se contredit lui-même.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=FRAIS_FACULTATIF, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("15000")


@pytest.mark.asyncio
async def test_un_trop_percu_n_eponge_pas_la_ligne_voisine(db: Session) -> None:
    """Le reste se plafonne ligne par ligne, jamais sur le total.

    80 000 posés sur un frais de 50 000 ne paient pas les 50 000 du frais
    d'à côté : compenser afficherait 20 000 de dette là où il en reste 50 000,
    et la caisse encaisserait le mauvais montant.
    """
    reste = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=TROP_PERCU, academic_year_id=ANNEE_COURANTE
    )
    assert reste == Decimal("50000")


@pytest.mark.asyncio
async def test_la_caisse_et_le_secretariat_voient_le_montant(db: Session) -> None:
    """`payments:read` SANS `payments:status:read` — le piège du projet.

    Le secrétariat et la caisse portent l'un sans l'autre. Un garde écrit
    « si l'état est permis alors l'alerte » les priverait de tout affichage,
    au guichet même où l'argent se réclame.
    """
    bloc = await fees_paid.arrears_outside_year(
        _Pont(db),
        student_id=ENDETTE,
        academic_year_id=ANNEE_COURANTE,
        finance=FinanceView.of(may_read_payments=True, may_read_status=False),
    )
    assert bloc["fees_arrears_other_years"] == Decimal("60000")
    assert bloc["has_arrears_other_years"] is True


@pytest.mark.asyncio
async def test_l_educateur_voit_l_alerte_sans_la_somme(db: Session) -> None:
    """`payments:status:read` seul : de quoi retenir un dossier, rien de plus.

    L'éducateur monte les réinscriptions sans manipuler l'argent. Il doit
    savoir qu'il reste quelque chose à régler ; le montant dit la situation
    économique du foyer et ne le regarde pas.
    """
    bloc = await fees_paid.arrears_outside_year(
        _Pont(db),
        student_id=ENDETTE,
        academic_year_id=ANNEE_COURANTE,
        finance=FinanceView.of(may_read_payments=False, may_read_status=True),
    )
    assert bloc["has_arrears_other_years"] is True
    assert bloc["fees_arrears_other_years"] is None, "un montant interdit vaut None, jamais 0"


@pytest.mark.asyncio
async def test_sans_aucun_droit_financier_rien_ne_sort(db: Session) -> None:
    """Ni montant ni alerte — et surtout pas un zéro.

    Un zéro se lirait « cette famille ne doit rien ailleurs », ce qui est
    faux : elle doit 60 000. `None` se lit « vous ne voyez pas cette
    information », et l'écran affiche un tiret honnête.
    """
    bloc = await fees_paid.arrears_outside_year(
        _Pont(db),
        student_id=ENDETTE,
        academic_year_id=ANNEE_COURANTE,
        finance=FinanceView.of(may_read_payments=False, may_read_status=False),
    )
    assert bloc["fees_arrears_other_years"] is None
    assert bloc["has_arrears_other_years"] is None


@pytest.mark.asyncio
async def test_les_deux_lectures_partent_du_meme_montant(db: Session) -> None:
    """Le bandeau et le refus doivent annoncer la même dette.

    Ils ont commencé par la calculer chacun de son côté — l'un sur tous les
    frais encore dus, l'autre sur les seuls frais obligatoires. Le même
    assistant de réinscription annonçait alors 300 000 F dans son bandeau et
    en opposait 180 000 dans son refus, et le seuil que la direction avait
    fixé en lisant le premier ne mordait pas là où elle croyait.

    Ce test tient l'invariant à la source : ce qu'une lecture somme sur les
    inscriptions d'un exercice donné vaut ce que l'autre en retire.
    """
    par_inscription = await fees_paid.remaining_by_enrollment(
        _Pont(db), student_id=FRAIS_FACULTATIF
    )
    total = sum(par_inscription.values(), Decimal("0"))

    hors_annee = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=FRAIS_FACULTATIF, academic_year_id=ANNEE_COURANTE
    )
    sans_retrait = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=FRAIS_FACULTATIF, academic_year_id=None
    )

    # Sans retrait, les deux lectures disent le meme nombre.
    assert sans_retrait == total
    # Le retrait ne fait qu'oter ce que l'ecran montre deja.
    assert hors_annee <= total


@pytest.mark.asyncio
async def test_un_dossier_clos_n_apporte_aucune_ligne(db: Session) -> None:
    """Zéro n'est pas une dette, et un dossier annulé n'en a plus du tout.

    Cet élève porte les deux : une inscription annulée sur l'exercice
    précédent, et une inscription vivante sur l'exercice courant. La lecture
    par inscription doit rendre la seconde et taire la première — sans quoi
    l'appelant qui nomme les exercices en dette citerait un dossier fermé.
    """
    par_inscription = await fees_paid.remaining_by_enrollment(_Pont(db), student_id=DOSSIER_CLOS)

    # L'inscription vivante est la seule a figurer : le dossier clos n'apporte
    # aucune ligne, et rien ne reste a devoir en dehors de l'annee courante.
    assert len(par_inscription) == 1
    hors_annee = await fees_paid.remaining_outside_year(
        _Pont(db), student_id=DOSSIER_CLOS, academic_year_id=ANNEE_COURANTE
    )
    assert hors_annee == Decimal("0")
