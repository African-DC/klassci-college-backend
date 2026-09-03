"""Le point par catégorie, mesuré en interrogeant une vraie base.

Les douze tests de `tests/routers/test_category_ledger_cloisonnement.py`
remplacent le service par un `AsyncMock` qui rend un document vide : ils
vérifient le câblage des permissions, et c'est utile, mais aucune ligne n'y
fait passer un versement réel dans le calcul. Or le défaut qu'on redoute sur
ce document n'est pas un défaut de câblage : c'est un montant faux.

Ce fichier somme donc pour de bon. La fixture a la forme que la caisse produit
depuis la migration 0028 : le versement n'existe QUE par son allocation,
`Payment.enrollment_fee_id` reste vide. Un calcul qui relirait l'ancienne
relation rendrait zéro partout, et chacun de ces tests le dirait.

Trois propriétés y sont tenues, et ce sont les trois que le document promet :

- **la période borne un événement, jamais un état** — ce qui est entré se
  filtre sur la fenêtre, ce qui reste dû se lit sur tout l'argent reçu ;
- **ce qui est entré se cloisonne, ce qui reste dû ne se cloisonne pas** — une
  caissière voit son encaissement à elle, et le reste dû se calcule quand même
  sur l'argent de toutes les caisses, sans quoi on relancerait une famille qui
  a payé au guichet d'à côté ;
- **l'effectif du périmètre est un dénominateur, pas une longueur de liste** —
  un élève qu'aucune ligne de frais ne couvre est compté, au lieu de
  disparaître du document et de le faire paraître complet.
"""

from collections.abc import Iterator
from datetime import date, datetime
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
from app.services import fee_category_ledger, fees_paid

ANNEE = 1
CLASSE_A = 1
CLASSE_B = 2
CATEGORIE = 7

AYA, BAKARY, CYRILLE, DJENEBA, EMERAUDE = 1, 2, 3, 4, 5
INSC_AYA, INSC_BAKARY, INSC_CYRILLE, INSC_DJENEBA, INSC_ANNULEE = 10, 11, 12, 13, 14
FRAIS_AYA, FRAIS_BAKARY, FRAIS_DJENEBA = 100, 101, 103

CAISSE_SOPHIE = 21
CAISSE_MARCEL = 22

OCTOBRE = datetime(2026, 10, 5, 9, 30)
NOVEMBRE = datetime(2026, 11, 5, 11, 0)
DEBUT_NOVEMBRE = datetime(2026, 11, 1)


class _Pont:
    """Donne l'allure d'une `AsyncSession` à une session synchrone.

    Le service n'utilise que `execute`. L'envelopper évite d'ajouter un pilote
    asynchrone pour faire tourner des tests qui ne mesurent que des montants.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _eleve(ident: int, nom: str, prenom: str) -> Student:
    return Student(id=ident, last_name=nom, first_name=prenom)


def _inscription(
    ident: int,
    eleve: int,
    classe: int,
    statut: str = EnrollmentStatus.VALIDE.value,
) -> Enrollment:
    return Enrollment(
        id=ident,
        student_id=eleve,
        class_id=classe,
        academic_year_id=ANNEE,
        status=statut,
    )


def _frais(
    ident: int,
    inscription: int,
    montant: str,
    statut: str = EnrollmentFeeStatus.PENDING.value,
) -> EnrollmentFee:
    return EnrollmentFee(
        id=ident,
        enrollment_id=inscription,
        fee_variant_id=1,
        fee_category_id=CATEGORIE,
        amount=Decimal(montant),
        status=statut,
    )


def _versement(
    ident: int,
    inscription: int,
    montant: str,
    statut: str,
    caisse: int,
    quand: datetime,
) -> Payment:
    """Un versement tel que la caisse le produit depuis 0028.

    `enrollment_fee_id` reste vide : le lien vers les frais ne passe que par
    les allocations.
    """
    return Payment(
        id=ident,
        enrollment_id=inscription,
        amount=Decimal(montant),
        method=PaymentMethod.CASH.value,
        status=statut,
        received_by=caisse,
        created_at=quand,
        enrollment_fee_id=None,
    )


@pytest.fixture()
def db() -> Iterator[Session]:
    """Une catégorie, quatre inscriptions ouvertes, trois lignes de frais.

    Cyrille est inscrit mais aucune ligne de cette catégorie ne le couvre :
    c'est lui que le document laissait tomber. L'inscription annulée, elle, ne
    doit compter dans aucun effectif.
    """
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=CLASSE_A, name="6eme A", level_id=1),
                Class(id=CLASSE_B, name="6eme B", level_id=1),
                _eleve(AYA, "KOUASSI", "Aya"),
                _eleve(BAKARY, "TRAORE", "Bakary"),
                _eleve(CYRILLE, "N'GUESSAN", "Cyrille"),
                _eleve(DJENEBA, "OUATTARA", "Djeneba"),
                _eleve(EMERAUDE, "ZADI", "Emeraude"),
                _inscription(INSC_AYA, AYA, CLASSE_A),
                _inscription(INSC_BAKARY, BAKARY, CLASSE_A),
                # Inscrit, jamais facture sur cette categorie.
                _inscription(INSC_CYRILLE, CYRILLE, CLASSE_A),
                _inscription(INSC_DJENEBA, DJENEBA, CLASSE_B),
                _inscription(
                    INSC_ANNULEE,
                    EMERAUDE,
                    CLASSE_A,
                    statut=EnrollmentStatus.ANNULE.value,
                ),
                FeeCategory(
                    id=CATEGORIE,
                    name="Paquet de rames",
                    priority=9,
                    is_mandatory=False,
                    accepts_in_kind=True,
                ),
                FeeVariant(
                    id=1,
                    fee_category_id=CATEGORIE,
                    academic_year_id=ANNEE,
                    amount=Decimal("3000"),
                ),
                _frais(FRAIS_AYA, INSC_AYA, "3000"),
                _frais(FRAIS_BAKARY, INSC_BAKARY, "3000"),
                _frais(FRAIS_DJENEBA, INSC_DJENEBA, "3000"),
            ]
        )
        s.flush()

        s.add_all(
            [
                # Sophie encaisse Aya en octobre, et solde sa ligne.
                _versement(
                    500,
                    INSC_AYA,
                    "3000",
                    PaymentStatus.COMPLETED.value,
                    CAISSE_SOPHIE,
                    OCTOBRE,
                ),
                # Marcel encaisse un acompte de Bakary en novembre.
                _versement(
                    501,
                    INSC_BAKARY,
                    "1000",
                    PaymentStatus.COMPLETED.value,
                    CAISSE_MARCEL,
                    NOVEMBRE,
                ),
                # Saisi mais pas encaisse : cet argent n'existe pas encore.
                _versement(
                    502,
                    INSC_BAKARY,
                    "2000",
                    PaymentStatus.PENDING.value,
                    CAISSE_SOPHIE,
                    NOVEMBRE,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                PaymentAllocation(
                    payment_id=500, enrollment_fee_id=FRAIS_AYA, amount=Decimal("3000")
                ),
                PaymentAllocation(
                    payment_id=501, enrollment_fee_id=FRAIS_BAKARY, amount=Decimal("1000")
                ),
                PaymentAllocation(
                    payment_id=502, enrollment_fee_id=FRAIS_BAKARY, amount=Decimal("2000")
                ),
            ]
        )
        s.commit()
        yield s


def _ligne(document: fee_category_ledger.CategoryLedger, frais: int) -> object:
    """La ligne d'un élève, retrouvée par son inscription."""
    par_inscription = {
        FRAIS_AYA: INSC_AYA,
        FRAIS_BAKARY: INSC_BAKARY,
        FRAIS_DJENEBA: INSC_DJENEBA,
    }
    return next(ligne for ligne in document.lignes if ligne.enrollment_id == par_inscription[frais])


# ---------------------------------------------------------------------------
# La règle de l'argent : une seule, et elle vit dans `fees_paid`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_versement_alloue_compte_comme_entre(db: Session) -> None:
    """Le versement n'existe que par son allocation ; il doit quand même entrer.

    C'est le bug fondateur de la migration 0028 : sommer l'ancienne relation
    rendrait zéro sous une ligne pourtant soldée.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_en_argent == Decimal("4000")
    assert document.eleves_en_argent == 2


@pytest.mark.asyncio
async def test_un_versement_non_encaisse_n_entre_pas(db: Session) -> None:
    """Tant que l'argent n'est pas encaissé, il n'est pas entré.

    Le filtre `completed` n'est plus retapé dans ce service : il vit dans
    `fees_paid`. Si le rapatriement l'avait perdu en chemin, les 2 000 F en
    attente de Bakary apparaîtraient ici, et sa ligne se dirait soldée.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_en_argent == Decimal("4000")
    assert _ligne(document, FRAIS_BAKARY).remaining == Decimal("2000")


@pytest.mark.asyncio
async def test_la_periode_borne_l_entre_mais_jamais_le_reste_du(db: Session) -> None:
    """« Qui n'a pas payé ce mois-ci » n'est pas « qui doit encore ».

    Sur novembre seul, le versement d'octobre d'Aya n'entre pas — c'est un
    événement, il est hors fenêtre. Mais sa ligne ne doit rien : le reste dû
    est un état, et le borner ferait réapparaître une dette réglée.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        date_from=DEBUT_NOVEMBRE,
    )

    assert document.total_en_argent == Decimal("1000")
    assert _ligne(document, FRAIS_AYA).paid == Decimal("0")
    assert _ligne(document, FRAIS_AYA).remaining == Decimal("0")


@pytest.mark.asyncio
async def test_l_argent_d_une_autre_caisse_sort_de_l_entre_et_reste_dans_le_du(
    db: Session,
) -> None:
    """La ligne de partage, prise par le montant.

    Sophie ne voit que ses 3 000 F. Mais l'acompte encaissé par Marcel doit
    continuer de réduire ce que Bakary doit : filtré sur une seule caisse, ce
    chiffre annoncerait 3 000 F de dette à une famille qui en a versé 1 000 au
    guichet d'à côté — et on irait la relancer.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        received_by=CAISSE_SOPHIE,
        consolide=True,
    )

    assert document.total_en_argent == Decimal("3000")
    assert _ligne(document, FRAIS_BAKARY).paid == Decimal("0")
    assert _ligne(document, FRAIS_BAKARY).remaining == Decimal("2000")
    assert document.total_restant_du == Decimal("5000")


@pytest.mark.asyncio
async def test_sans_le_droit_de_lire_toutes_les_caisses_le_du_est_absent(db: Session) -> None:
    """Absent, pas zéro : un zéro se lirait comme un solde."""
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        received_by=CAISSE_SOPHIE,
        consolide=False,
    )

    assert document.total_restant_du is None
    assert document.eleves_restant_du is None
    assert all(ligne.remaining is None for ligne in document.lignes)


@pytest.mark.asyncio
async def test_aucun_frais_demande_ne_part_pas_en_base(db: Session) -> None:
    """`IN ()` n'a rien à faire dans une requête, et certains moteurs le refusent."""
    assert await fees_paid.paid_by_fee_ids(_Pont(db), fee_ids=[]) == {}


@pytest.mark.asyncio
async def test_le_verse_borne_se_lit_par_la_fonction_canonique(db: Session) -> None:
    """La fenêtre et la caisse portent bien sur le socle commun.

    Le service ne calcule plus lui-même : si `paid_by_fee_ids` cessait
    d'appliquer l'un des deux filtres, le document le suivrait sans broncher.
    """
    tous = await fees_paid.paid_by_fee_ids(_Pont(db), fee_ids=[FRAIS_AYA, FRAIS_BAKARY])
    assert tous == {FRAIS_AYA: Decimal("3000"), FRAIS_BAKARY: Decimal("1000")}

    chez_sophie = await fees_paid.paid_by_fee_ids(
        _Pont(db), fee_ids=[FRAIS_AYA, FRAIS_BAKARY], received_by=CAISSE_SOPHIE
    )
    assert chez_sophie == {FRAIS_AYA: Decimal("3000")}

    en_novembre = await fees_paid.paid_by_fee_ids(
        _Pont(db), fee_ids=[FRAIS_AYA, FRAIS_BAKARY], date_from=DEBUT_NOVEMBRE
    )
    assert en_novembre == {FRAIS_BAKARY: Decimal("1000")}


# ---------------------------------------------------------------------------
# L'effectif du périmètre, et ceux qu'aucune ligne ne couvre
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_eleve_sans_ligne_de_frais_est_compte_et_non_perdu(db: Session) -> None:
    """Cyrille est inscrit et n'a jamais été facturé sur cette catégorie.

    Il n'apparaît dans aucune ligne : sans ce compte, le document se lisait
    comme si tout le monde était couvert, et son dénominateur rétrécissait
    sans que rien ne le dise.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.effectif_perimetre == 4
    assert len(document.lignes) == 3
    assert document.eleves_sans_ligne == 1


@pytest.mark.asyncio
async def test_l_effectif_suit_le_perimetre_demande(db: Session) -> None:
    """Réduire à une classe réduit le dénominateur, pas seulement la liste."""
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, class_id=CLASSE_A
    )

    assert document.effectif_perimetre == 3
    assert len(document.lignes) == 2
    assert document.eleves_sans_ligne == 1


@pytest.mark.asyncio
async def test_une_inscription_close_ne_pese_dans_aucun_effectif(db: Session) -> None:
    """Un dossier annulé ne doit rien et n'a pas à gonfler un dénominateur.

    Emeraude est annulée : la compter ferait apparaître un élève non facturé
    de plus, et donc un trou de facturation qui n'existe pas.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, class_id=CLASSE_A
    )

    assert document.effectif_perimetre == 3


@pytest.mark.asyncio
async def test_l_effectif_ne_se_cloisonne_pas(db: Session) -> None:
    """Ce sont des inscriptions, pas de l'argent.

    Une caissière a le droit de savoir combien d'élèves son document aurait dû
    couvrir : le lui refuser ne protégerait rien et l'empêcherait de voir
    qu'une classe entière manque à l'appel.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        received_by=CAISSE_SOPHIE,
        consolide=False,
    )

    assert document.effectif_perimetre == 4
    assert document.eleves_sans_ligne == 1


@pytest.mark.asyncio
async def test_le_compte_des_sans_ligne_ne_vient_pas_de_la_liste_rendue(db: Session) -> None:
    """L'addition doit retomber sur ses pieds, quoi qu'il arrive à la liste.

    Le compte est un agrégat sur le périmètre entier, pas une soustraction
    faite sur `lignes`. Le jour où la liste sera paginée — et le plan le
    prévoit — un chiffre tiré de la page baisserait à chaque page tournée.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    couverts = document.effectif_perimetre - document.eleves_sans_ligne
    assert couverts == len(document.lignes)
