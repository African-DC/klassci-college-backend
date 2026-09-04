"""Le point par catégorie, mesuré en interrogeant une vraie base.

Les douze tests de `tests/routers/test_category_ledger_cloisonnement.py`
remplacent le service par un `AsyncMock` qui rend un document vide : ils
vérifient le câblage des permissions, et c'est utile, mais aucune ligne n'y
fait passer un versement réel dans le calcul. Or le défaut qu'on redoute sur
ce document n'est pas un défaut de câblage : c'est un montant faux.

Ce fichier somme donc pour de bon. Les fixtures ont la forme que la caisse
produit depuis la migration 0028 : le versement n'existe QUE par son
allocation, `Payment.enrollment_fee_id` reste vide. Un calcul qui relirait
l'ancienne relation rendrait zéro partout, et chacun de ces tests le dirait.

Quatre propriétés y sont tenues, et ce sont celles que le document promet :

- **la période borne un événement, jamais un état** — l'argent entré et les
  dépôts reçus se filtrent sur la fenêtre ; les états, l'attendu et le reste dû
  se lisent sur tout ce qui a été reçu, sans borne ;
- **ce qui est entré se cloisonne, ce qui reste dû ne se cloisonne pas** — une
  caissière voit son encaissement à elle, dépôts en nature compris, et le reste
  dû se calcule quand même sur l'argent de toutes les caisses, sans quoi on
  relancerait une famille qui a payé au guichet d'à côté ;
- **l'effectif du périmètre est un dénominateur, pas une longueur de liste** —
  un élève qu'aucune ligne de frais ne couvre est compté, au lieu de
  disparaître du document et de le faire paraître complet ;
- **un versement compte une fois par catégorie, et un versement annulé nulle
  part** — un acte de caisse peut se partager entre deux frais, et le document
  de chacun ne doit voir que sa part.

Deux décors, parce qu'un seul ne pouvait pas dire les deux dernières : `db`
porte une catégorie et une école entière, `caisse` porte deux catégories, un
versement réparti, un versement annulé et deux dépôts faits à deux guichets.
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import BigInteger, create_engine, update
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import BusinessValidationError
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


def _eleve(ident: int, nom: str, prenom: str, matricule: str) -> Student:
    """Un élève avec son matricule : la recherche cherche aussi là-dedans.

    Le modèle remplit `last_name_key` / `first_name_key` à l'écriture — c'est
    sur ces colonnes-là que la recherche porte, et les fabriquer ici à la main
    reviendrait à écrire un second repliage.
    """
    return Student(id=ident, last_name=nom, first_name=prenom, enrollment_number=matricule)


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
    *,
    categorie: int = CATEGORIE,
    variante: int = 1,
    depose_par: int | None = None,
    depose_le: datetime | None = None,
) -> EnrollmentFee:
    """Une ligne de frais. `depose_*` ne vaut que pour un dépôt en nature.

    Le dépôt porte SA caisse (`deposited_by_user_id`) comme un versement porte
    la sienne : c'est ce qui permet de vérifier qu'il se cloisonne pareil.
    """
    return EnrollmentFee(
        id=ident,
        enrollment_id=inscription,
        fee_variant_id=variante,
        fee_category_id=categorie,
        amount=Decimal(montant),
        status=statut,
        deposited_by_user_id=depose_par,
        deposited_at=depose_le,
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


@compiles(BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):  # noqa: ARG001
    """SQLite n'a pas de BIGINT auto-incrémenté : c'est INTEGER, ou rien."""
    return "INTEGER"


def _base_vierge() -> Session:
    """Une base neuve au schéma réel. Deux fixtures s'en servent.

    Chacune peuple son propre décor : le point par catégorie et le versement
    réparti sur deux catégories ne peuvent pas partager le leur, la seconde
    ajoutant justement de l'argent là où la première compte le sien.
    """
    moteur = create_engine("sqlite://")
    Base.metadata.create_all(moteur)
    return Session(moteur)


@pytest.fixture()
def db() -> Iterator[Session]:
    """Une catégorie, quatre inscriptions ouvertes, trois lignes de frais.

    Cyrille est inscrit mais aucune ligne de cette catégorie ne le couvre :
    c'est lui que le document laissait tomber. L'inscription annulée, elle, ne
    doit compter dans aucun effectif.
    """
    with _base_vierge() as s:
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
                _eleve(AYA, "KOUASSI", "Aya", "C-2026-001"),
                # Accentue, comme sur la piece d'etat civil : la recherche doit
                # le trouver sans que la personne pense a taper l'accent.
                _eleve(BAKARY, "TRAORÉ", "Bakary", "C-2026-002"),
                _eleve(CYRILLE, "N'GUESSAN", "Cyrille", "C-2026-003"),
                _eleve(DJENEBA, "OUATTARA", "Djeneba", "C-2026-004"),
                _eleve(EMERAUDE, "ZADI", "Emeraude", "C-2026-005"),
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
                # Les statuts sont ceux que `recompute_fee_status` poserait au
                # vu des versements plus bas : Aya soldée, Bakary à moitié,
                # Djeneba n'a rien donné. C'est de ce champ-là, et de lui seul,
                # que sortent les seaux.
                _frais(FRAIS_AYA, INSC_AYA, "3000", EnrollmentFeeStatus.PAID.value),
                _frais(FRAIS_BAKARY, INSC_BAKARY, "3000", EnrollmentFeeStatus.PARTIAL.value),
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


# ---------------------------------------------------------------------------
# L'attendu, le taux, les seaux — l'addition qui manquait
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_total_attendu_additionne_ce_qui_est_encore_du(db: Session) -> None:
    """La donnée était là, ligne par ligne ; c'est l'addition qui manquait.

    Sans elle le document n'a pas de dénominateur, et il n'est montrable à
    aucune direction : on y lit ce qui est rentré sans savoir sur quoi.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_attendu == Decimal("9000")


@pytest.mark.asyncio
async def test_le_taux_est_le_recouvre_sur_l_attendu(db: Session) -> None:
    """4 000 F recouvrés sur 9 000 attendus, à une décimale comme ailleurs.

    Le recouvré n'est pas une seconde somme d'allocations : c'est l'attendu
    moins ce qui reste dû. Les 2 000 F saisis mais non encaissés de Bakary
    n'entrent donc nulle part, ni au numérateur ni au dénominateur.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_restant_du == Decimal("5000")
    assert document.taux_recouvrement == 44.4


@pytest.mark.asyncio
async def test_une_exoneration_sort_du_denominateur_ET_du_numerateur(db: Session) -> None:
    """Le piège du taux qui dépasse 100 %, pris par les montants.

    Aya a versé ses 3 000 F, puis l'école l'exonère. Sa ligne n'est plus due :
    elle sort de l'attendu. Si son argent restait au numérateur, on lirait
    4 000 recouvrés sur 6 000 attendus — 66,7 % — alors que seul Bakary a
    versé sur les lignes encore dues, soit 1 000 sur 6 000.
    """
    db.execute(
        update(EnrollmentFee)
        .where(EnrollmentFee.id == FRAIS_AYA)
        .values(status=EnrollmentFeeStatus.WAIVED.value)
    )
    db.commit()

    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_attendu == Decimal("6000")
    assert document.taux_recouvrement == 16.7


@pytest.mark.asyncio
async def test_le_taux_ne_depasse_jamais_cent_pour_cent(db: Session) -> None:
    """Tout ce qui reste dû est soldé : cent, et pas un point de plus."""
    db.execute(
        update(EnrollmentFee)
        .where(EnrollmentFee.id.in_([FRAIS_BAKARY, FRAIS_DJENEBA]))
        .values(status=EnrollmentFeeStatus.WAIVED.value)
    )
    db.commit()

    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_attendu == Decimal("3000")
    assert document.taux_recouvrement == 100.0


@pytest.mark.asyncio
async def test_un_taux_sans_denominateur_est_absent_et_non_nul(db: Session) -> None:
    """Plus rien n'est dû en argent : le taux n'existe pas, il ne vaut pas zéro.

    Zéro se lirait « rien n'est rentré », ce qui est le contraire de la
    situation. L'attendu, lui, vaut bien zéro : c'est un fait connu.
    """
    db.execute(update(EnrollmentFee).values(status=EnrollmentFeeStatus.WAIVED.value))
    db.commit()

    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.total_attendu == Decimal("0")
    assert document.taux_recouvrement is None


@pytest.mark.asyncio
async def test_les_compteurs_par_seau_retombent_sur_le_nombre_de_lignes(db: Session) -> None:
    """Un compteur d'onglet qui ne retombe pas sur la liste fait douter des deux."""
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert document.compteurs == {
        "pending": 1,
        "partial": 1,
        "paid": 1,
        "waived": 0,
        "in_kind": 0,
    }
    couverts = document.effectif_perimetre - document.eleves_sans_ligne
    assert sum(document.compteurs.values()) == couverts


@pytest.mark.asyncio
async def test_le_recouvrement_entier_est_absent_pour_une_caissiere(db: Session) -> None:
    """Le taux, l'attendu et les seaux forment un bloc, et il ne se sert pas à moitié.

    Un taux calculé sur une seule caisse annoncerait une dette chez des
    familles ayant payé au guichet d'à côté. Ce qu'elle garde, c'est son
    encaissement à elle — un fait sur sa caisse.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        received_by=CAISSE_SOPHIE,
        consolide=False,
    )

    assert document.total_attendu is None
    assert document.taux_recouvrement is None
    assert document.compteurs is None
    assert document.total_en_argent == Decimal("3000")
    assert document.effectif_perimetre == 4


# ---------------------------------------------------------------------------
# Le seau, la recherche, la page et le plafond
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_seau_filtre_la_liste_sans_deplacer_les_compteurs(db: Session) -> None:
    """Les compteurs décrivent le périmètre, la liste décrit l'onglet ouvert.

    Sinon le chiffre de l'onglet vaudrait toujours la longueur de sa propre
    liste, et les trois onglets afficheraient chacun cent pour cent d'eux-mêmes.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        state=fee_category_ledger.SEAU_IMPAYES,
    )

    assert {ligne.enrollment_id for ligne in document.lignes} == {INSC_BAKARY, INSC_DJENEBA}
    assert document.total_lignes == 2
    assert document.etat_filtre == fee_category_ledger.SEAU_IMPAYES
    # Le périmètre, intact.
    assert document.compteurs is not None
    assert sum(document.compteurs.values()) == 3
    assert document.total_en_argent == Decimal("4000")
    assert document.total_attendu == Decimal("9000")


@pytest.mark.asyncio
async def test_le_seau_sort_du_statut_et_non_du_verse_affiche(db: Session) -> None:
    """Bakary a versé chez Marcel ; lu depuis la caisse de Sophie, son versé est nul.

    Classer sur ce versé-là mettrait Aya — soldée au guichet d'à côté — dans
    « aucun paiement ». Le statut, lui, est recalculé sur tout l'argent reçu :
    c'est le seul champ dont un seau puisse sortir.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        received_by=CAISSE_MARCEL,
        consolide=True,
        state=EnrollmentFeeStatus.PAID.value,
    )

    assert _ligne(document, FRAIS_AYA).paid == Decimal("0")
    assert {ligne.enrollment_id for ligne in document.lignes} == {INSC_AYA}


@pytest.mark.asyncio
async def test_le_tri_par_seau_se_refuse_a_une_caissiere(db: Session) -> None:
    """Un refus explicite, pas une liste vide qu'on lirait « personne ne doit rien »."""
    with pytest.raises(BusinessValidationError):
        await fee_category_ledger.load_category_ledger(
            _Pont(db),
            category_id=CATEGORIE,
            academic_year_id=ANNEE,
            received_by=CAISSE_SOPHIE,
            consolide=False,
            state=fee_category_ledger.SEAU_IMPAYES,
        )


@pytest.mark.asyncio
async def test_un_seau_inconnu_est_refuse_et_non_ignore(db: Session) -> None:
    """Un filtre silencieusement ignoré rendrait la liste entière sous son nom."""
    with pytest.raises(BusinessValidationError):
        await fee_category_ledger.load_category_ledger(
            _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, state="en_retard"
        )


@pytest.mark.asyncio
async def test_la_recherche_se_moque_de_la_casse_et_des_accents(db: Session) -> None:
    """« TRAORÉ » doit se trouver en tapant « traore ».

    La recherche porte sur la forme comparable que l'élève porte déjà en
    colonne. Sur le nom brut, la fiche resterait introuvable sous son propre
    nom — et on la recréerait, avec une seconde ardoise.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="traore"
    )

    assert [ligne.enrollment_id for ligne in document.lignes] == [INSC_BAKARY]
    assert document.total_lignes == 1
    assert document.recherche == "traore"


@pytest.mark.asyncio
async def test_la_recherche_trouve_par_matricule(db: Session) -> None:
    """C'est ce que la caisse a sous les yeux quand la famille tend son carnet."""
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="C-2026-004"
    )

    assert [ligne.enrollment_id for ligne in document.lignes] == [INSC_DJENEBA]


@pytest.mark.asyncio
async def test_chaque_mot_cherche_doit_correspondre(db: Session) -> None:
    """Les mots se cumulent : « a Djeneba » ne rend pas tout le monde.

    Les trois noms de la liste portent un « a ». Un `OU` entre les mots ferait
    donc remonter la classe entière dès qu'un mot est large, et la recherche
    cesserait de servir à sa deuxième lettre.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="a Djeneba"
    )

    assert [ligne.enrollment_id for ligne in document.lignes] == [INSC_DJENEBA]
    assert document.total_lignes == 1
    assert document.recherche_approchee is False


@pytest.mark.asyncio
async def test_le_repechage_flou_rattrape_une_faute_de_frappe(db: Session) -> None:
    """« KOUASI » pour « KOUASSI » : une page vide se lirait « pas dans cette classe ».

    Même dernier recours que la liste des élèves : la recherche exacte
    d'abord, le flou seulement quand elle n'a rien rendu.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="KOUASI"
    )

    assert [ligne.enrollment_id for ligne in document.lignes] == [INSC_AYA]
    assert document.total_lignes == 1


@pytest.mark.asyncio
async def test_le_repechage_dit_qu_il_est_un_repechage(db: Session) -> None:
    """Des fiches approchantes servies sans un mot se lisent comme LA réponse.

    Et on encaisse alors sur l'homonyme. Le drapeau existe pour que l'écran
    écrive « aucune correspondance exacte » au-dessus de ces lignes-là.
    """
    exacte = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="traore"
    )
    approchee = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, q="KOUASI"
    )

    assert exacte.recherche_approchee is False
    assert approchee.recherche_approchee is True


@pytest.mark.asyncio
async def test_les_totaux_ne_baissent_pas_quand_on_tourne_la_page(db: Session) -> None:
    """Le défaut qui rend une pagination pire que pas de pagination du tout.

    Les lignes sortent triées sur le nom : KOUASSI, OUATTARA, TRAORÉ. La
    deuxième page d'une page à une ligne montre donc Djeneba — et les chiffres
    du haut décrivent toujours l'école entière.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, page=2, size=1
    )

    assert [ligne.enrollment_id for ligne in document.lignes] == [INSC_DJENEBA]
    assert document.total_lignes == 3
    assert document.page == 2
    assert document.size == 1
    assert document.total_en_argent == Decimal("4000")
    assert document.total_attendu == Decimal("9000")
    assert document.effectif_perimetre == 4


@pytest.mark.asyncio
async def test_le_plafond_coupe_la_liste_et_le_document_le_dit(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un document amputé qui se tait vaut moins qu'un document absent.

    Le plafond réel est à cinq mille lignes ; on l'abaisse ici pour mesurer le
    comportement plutôt que la constante.
    """
    monkeypatch.setattr(fee_category_ledger, "LEDGER_MAX_ROWS", 2)

    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE
    )

    assert len(document.lignes) == 2
    assert document.total_lignes == 3
    assert document.truncated_from == 3


@pytest.mark.asyncio
async def test_tourner_une_page_n_est_pas_une_troncature(db: Session) -> None:
    """`truncated_from` dit que le plafond a coupé, pas qu'il reste des pages."""
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=CATEGORIE, academic_year_id=ANNEE, page=1, size=1
    )

    assert len(document.lignes) == 1
    assert document.total_lignes == 3
    assert document.truncated_from is None


@pytest.mark.asyncio
async def test_le_nom_de_la_classe_vient_du_critere_et_non_des_lignes(db: Session) -> None:
    """Un filtre peut vider la page ; il ne doit pas effacer le nom du périmètre.

    Reconstitué depuis la première ligne rendue, ce nom disparaissait
    exactement quand le document en avait le plus besoin : au-dessus d'une
    liste vide, pour dire de quelle classe elle est vide.
    """
    document = await fee_category_ledger.load_category_ledger(
        _Pont(db),
        category_id=CATEGORIE,
        academic_year_id=ANNEE,
        class_id=CLASSE_A,
        q="ZZZZZZ",
    )

    assert document.lignes == ()
    assert document.class_name == "6eme A"


# ---------------------------------------------------------------------------
# L'agrégat : ce qui ADDITIONNE, sur deux catégories et deux caisses
#
# Le décor précédent ne porte qu'une catégorie et pas un seul dépôt en nature :
# il ne peut donc dire ni qu'un versement réparti compte une fois de chaque
# côté, ni qu'un dépôt se cloisonne comme de l'argent. C'est le décor de la
# vraie caisse — un versement qui se partage, un versement annulé, deux dépôts
# faits par deux guichets différents.
# ---------------------------------------------------------------------------

CAT_INSCRIPTION = 30
CAT_RAMES = 31
VAR_INSCRIPTION = 70
VAR_RAMES = 71

FATOU, ISMAEL, KOFFI, LASSINA = 41, 42, 43, 44
INSC_FATOU, INSC_ISMAEL, INSC_KOFFI, INSC_LASSINA = 50, 51, 52, 53
FRAIS_FATOU_INSCRIPTION = 60
FRAIS_FATOU_RAMES = 61
FRAIS_ISMAEL_INSCRIPTION = 62
FRAIS_KOFFI_RAMES = 63
FRAIS_LASSINA_RAMES = 64


@pytest.fixture()
def caisse() -> Iterator[Session]:
    """Deux catégories, un versement réparti, un versement annulé, deux dépôts.

    Fatou verse 5 000 F en une fois chez Sophie : 2 000 sur l'Inscription,
    3 000 sur les Rames. C'est un seul acte de caisse et deux imputations, et
    c'est la forme que la migration 0028 a rendue normale.

    Ismaël a un versement ANNULÉ de 30 000 F, allocation comprise : l'annulation
    ne supprime pas les lignes, elle change l'état du versement. Un total qui
    perdrait le filtre `completed` le ferait ressusciter et solderait sa dette.

    Koffi a déposé ses rames au guichet de Sophie en octobre, Lassina à celui de
    Marcel en novembre : deux dépôts, deux caisses, deux mois.
    """
    with _base_vierge() as s:
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
                _eleve(FATOU, "BAMBA", "Fatou", "C-2026-011"),
                _eleve(ISMAEL, "COULIBALY", "Ismael", "C-2026-012"),
                _eleve(KOFFI, "KOFFI", "Yao", "C-2026-013"),
                _eleve(LASSINA, "SANOGO", "Lassina", "C-2026-014"),
                _inscription(INSC_FATOU, FATOU, CLASSE_A),
                _inscription(INSC_ISMAEL, ISMAEL, CLASSE_A),
                _inscription(INSC_KOFFI, KOFFI, CLASSE_A),
                _inscription(INSC_LASSINA, LASSINA, CLASSE_A),
                FeeCategory(
                    id=CAT_INSCRIPTION,
                    name="Inscription",
                    priority=10,
                    is_mandatory=True,
                    accepts_in_kind=False,
                ),
                FeeCategory(
                    id=CAT_RAMES,
                    name="Paquet de rames",
                    priority=90,
                    is_mandatory=False,
                    accepts_in_kind=True,
                ),
                FeeVariant(
                    id=VAR_INSCRIPTION,
                    fee_category_id=CAT_INSCRIPTION,
                    academic_year_id=ANNEE,
                    amount=Decimal("30000"),
                ),
                FeeVariant(
                    id=VAR_RAMES,
                    fee_category_id=CAT_RAMES,
                    academic_year_id=ANNEE,
                    amount=Decimal("3000"),
                ),
                _frais(
                    FRAIS_FATOU_INSCRIPTION,
                    INSC_FATOU,
                    "30000",
                    EnrollmentFeeStatus.PARTIAL.value,
                    categorie=CAT_INSCRIPTION,
                    variante=VAR_INSCRIPTION,
                ),
                _frais(
                    FRAIS_FATOU_RAMES,
                    INSC_FATOU,
                    "3000",
                    EnrollmentFeeStatus.PAID.value,
                    categorie=CAT_RAMES,
                    variante=VAR_RAMES,
                ),
                _frais(
                    FRAIS_ISMAEL_INSCRIPTION,
                    INSC_ISMAEL,
                    "30000",
                    categorie=CAT_INSCRIPTION,
                    variante=VAR_INSCRIPTION,
                ),
                _frais(
                    FRAIS_KOFFI_RAMES,
                    INSC_KOFFI,
                    "3000",
                    EnrollmentFeeStatus.IN_KIND.value,
                    categorie=CAT_RAMES,
                    variante=VAR_RAMES,
                    depose_par=CAISSE_SOPHIE,
                    depose_le=OCTOBRE,
                ),
                _frais(
                    FRAIS_LASSINA_RAMES,
                    INSC_LASSINA,
                    "3000",
                    EnrollmentFeeStatus.IN_KIND.value,
                    categorie=CAT_RAMES,
                    variante=VAR_RAMES,
                    depose_par=CAISSE_MARCEL,
                    depose_le=NOVEMBRE,
                ),
            ]
        )
        s.flush()

        s.add_all(
            [
                # UN acte de caisse, DEUX imputations.
                _versement(
                    600,
                    INSC_FATOU,
                    "5000",
                    PaymentStatus.COMPLETED.value,
                    CAISSE_SOPHIE,
                    OCTOBRE,
                ),
                # Encaisse puis annule : la ligne reste, l'argent non.
                _versement(
                    601,
                    INSC_ISMAEL,
                    "30000",
                    PaymentStatus.CANCELLED.value,
                    CAISSE_SOPHIE,
                    NOVEMBRE,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                PaymentAllocation(
                    payment_id=600,
                    enrollment_fee_id=FRAIS_FATOU_INSCRIPTION,
                    amount=Decimal("2000"),
                ),
                PaymentAllocation(
                    payment_id=600,
                    enrollment_fee_id=FRAIS_FATOU_RAMES,
                    amount=Decimal("3000"),
                ),
                PaymentAllocation(
                    payment_id=601,
                    enrollment_fee_id=FRAIS_ISMAEL_INSCRIPTION,
                    amount=Decimal("30000"),
                ),
            ]
        )
        s.commit()
        yield s


async def _point(
    db: Session, categorie: int, **criteres: Any
) -> fee_category_ledger.CategoryLedger:
    """Le point d'une catégorie sur ce décor-là."""
    return await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=categorie, academic_year_id=ANNEE, **criteres
    )


def _par_frais(document: fee_category_ledger.CategoryLedger, frais: int) -> object:
    """La ligne d'un frais, retrouvée par l'inscription qui le porte."""
    par_inscription = {
        FRAIS_FATOU_INSCRIPTION: INSC_FATOU,
        FRAIS_FATOU_RAMES: INSC_FATOU,
        FRAIS_ISMAEL_INSCRIPTION: INSC_ISMAEL,
        FRAIS_KOFFI_RAMES: INSC_KOFFI,
        FRAIS_LASSINA_RAMES: INSC_LASSINA,
    }
    return next(ligne for ligne in document.lignes if ligne.enrollment_id == par_inscription[frais])


@pytest.mark.asyncio
async def test_un_versement_reparti_compte_une_fois_dans_chaque_categorie(
    caisse: Session,
) -> None:
    """Les 5 000 F de Fatou valent 2 000 sur l'Inscription et 3 000 sur les Rames.

    Une fois dans chacune, jamais deux fois dans l'une : c'est la faute qu'un
    total lu sur `Payment.amount` plutôt que sur ses allocations commettrait
    dans les deux sens à la fois — 3 000 F de trop d'un côté, 2 000 F de trop
    de l'autre, et un point par catégorie qui somme plus que la caisse.
    """
    inscription = await _point(caisse, CAT_INSCRIPTION)
    rames = await _point(caisse, CAT_RAMES)

    assert inscription.total_en_argent == Decimal("2000")
    assert rames.total_en_argent == Decimal("3000")
    assert _par_frais(inscription, FRAIS_FATOU_INSCRIPTION).paid == Decimal("2000")
    assert _par_frais(rames, FRAIS_FATOU_RAMES).paid == Decimal("3000")
    # Un seul élève est entré de chaque côté : c'est la même personne, comptée
    # une fois par catégorie et non deux fois dans la même.
    assert inscription.eleves_en_argent == 1
    assert rames.eleves_en_argent == 1
    # Et l'acte de caisse se retrouve entier quand on rassemble les deux.
    assert inscription.total_en_argent + rames.total_en_argent == Decimal("5000")


@pytest.mark.asyncio
async def test_le_reste_du_d_un_versement_reparti_ne_voit_que_sa_part(
    caisse: Session,
) -> None:
    """Chaque dette ne se réduit que de ce qui lui a été imputé.

    Les 5 000 F ne soldent pas les rames ET l'inscription : la ligne
    d'inscription reste due de 28 000 F, celle des rames de rien.
    """
    inscription = await _point(caisse, CAT_INSCRIPTION)
    rames = await _point(caisse, CAT_RAMES)

    assert _par_frais(inscription, FRAIS_FATOU_INSCRIPTION).remaining == Decimal("28000")
    assert _par_frais(rames, FRAIS_FATOU_RAMES).remaining == Decimal("0")


@pytest.mark.asyncio
async def test_un_versement_annule_ne_compte_nulle_part(caisse: Session) -> None:
    """L'annulation laisse la ligne d'allocation ; elle ne doit rendre aucun franc.

    Ni dans l'entré — Ismaël n'a rien versé —, ni dans le reste dû, où
    l'oublier aurait l'effet inverse et bien pire : sa dette de 30 000 F
    passerait pour soldée, et personne n'irait plus la réclamer.
    """
    document = await _point(caisse, CAT_INSCRIPTION)
    ligne = _par_frais(document, FRAIS_ISMAEL_INSCRIPTION)

    assert ligne.paid == Decimal("0")
    assert ligne.remaining == Decimal("30000")
    assert ligne.status == EnrollmentFeeStatus.PENDING.value
    # Et l'agrégat ne le compte pas davantage que la ligne.
    assert document.total_en_argent == Decimal("2000")
    assert document.eleves_en_argent == 1
    assert document.total_restant_du == Decimal("58000")
    assert document.eleves_restant_du == 2


@pytest.mark.asyncio
async def test_un_versement_annule_ne_gonfle_pas_le_taux(caisse: Session) -> None:
    """Le taux se lit sur l'attendu et le reste dû, et l'annulé ne bouge ni l'un ni l'autre.

    60 000 F attendus, 58 000 F encore dus : 3,3 %. Compter l'argent rendu
    afficherait 53,3 %, et une école qui recouvre la moitié de son inscription
    ne relance pas comme une école qui n'en a rien recouvré.
    """
    document = await _point(caisse, CAT_INSCRIPTION)

    assert document.total_attendu == Decimal("60000")
    assert document.taux_recouvrement == 3.3


@pytest.mark.asyncio
async def test_le_cloisonnement_porte_sur_le_depot_comme_sur_l_argent(
    caisse: Session,
) -> None:
    """Un dépôt est quelque chose qui est ENTRÉ : il suit la ligne de partage.

    Le document affirme en toutes lettres ne couvrir que la caisse qui le tire.
    Un compteur de dépôts qui, lui, couvrirait l'école entière ferait dire au
    même document deux périmètres à la fois — et c'est le stock que la
    comptable irait ensuite chercher au magasin.
    """
    chez_sophie = await _point(caisse, CAT_RAMES, received_by=CAISSE_SOPHIE)
    chez_marcel = await _point(caisse, CAT_RAMES, received_by=CAISSE_MARCEL)
    toutes_caisses = await _point(caisse, CAT_RAMES)

    assert chez_sophie.depots_en_nature == 1
    assert chez_marcel.depots_en_nature == 1
    assert toutes_caisses.depots_en_nature == 2
    # L'argent se cloisonne au même endroit : Sophie a encaissé les rames de
    # Fatou, Marcel n'a encaissé aucun franc sur cette catégorie.
    assert chez_sophie.total_en_argent == Decimal("3000")
    assert chez_marcel.total_en_argent == Decimal("0")


@pytest.mark.asyncio
async def test_pour_une_caisse_cloisonnee_l_entre_reste_et_le_du_est_absent(
    caisse: Session,
) -> None:
    """Ce qui est entré est un fait sur sa caisse ; ce qui reste dû ne l'est pas.

    Marcel garde donc son dépôt — un chiffre vrai, qu'il est seul à pouvoir
    justifier — et perd le reste dû, l'attendu, le taux et les compteurs. Aucun
    de ces quatre-là ne descend à zéro au passage : un zéro se lirait comme un
    solde, et « personne ne doit rien » est le contraire de « je ne peux pas
    savoir ».
    """
    document = await _point(caisse, CAT_RAMES, received_by=CAISSE_MARCEL, consolide=False)

    assert document.depots_en_nature == 1
    assert document.total_en_argent == Decimal("0")
    assert document.effectif_perimetre == 4
    assert document.total_restant_du is None
    assert document.eleves_restant_du is None
    assert document.total_attendu is None
    assert document.taux_recouvrement is None
    assert document.compteurs is None
    assert all(ligne.remaining is None for ligne in document.lignes)


@pytest.mark.asyncio
async def test_la_periode_borne_le_depot_comme_le_versement(caisse: Session) -> None:
    """Un dépôt a une date : c'est un événement, et il se borne.

    Sur novembre seul, celui de Koffi — remis en octobre — n'est pas entré ce
    mois-là. Le compter quand même ferait annoncer au point de novembre un
    stock qui n'y est pas arrivé.
    """
    document = await _point(caisse, CAT_RAMES, date_from=DEBUT_NOVEMBRE)

    assert document.depots_en_nature == 1
    assert document.total_en_argent == Decimal("0")


@pytest.mark.asyncio
async def test_la_periode_ne_borne_ni_l_etat_des_lignes_ni_l_attendu(
    caisse: Session,
) -> None:
    """« Ce qui est rentré en novembre » n'est pas « où en sont les lignes ».

    La fenêtre déplace l'entré et les dépôts comptés ; elle ne doit toucher ni
    les états, ni l'attendu, ni le reste dû. Sinon la ligne soldée de Fatou
    redeviendrait due le mois suivant, et les deux rames déjà remises
    repasseraient au magasin.
    """
    document = await _point(caisse, CAT_RAMES, date_from=DEBUT_NOVEMBRE)

    assert document.compteurs == {
        "pending": 0,
        "partial": 0,
        "paid": 1,
        "waived": 0,
        "in_kind": 2,
    }
    assert document.total_attendu == Decimal("3000")
    assert document.total_restant_du == Decimal("0")
    assert document.taux_recouvrement == 100.0
    ligne = _par_frais(document, FRAIS_FATOU_RAMES)
    assert ligne.status == EnrollmentFeeStatus.PAID.value
    assert ligne.paid == Decimal("0")
    assert ligne.remaining == Decimal("0")


@pytest.mark.asyncio
async def test_un_depot_n_est_pas_de_l_argent_et_sort_de_l_attendu(
    caisse: Session,
) -> None:
    """Deux rames remises ne sont pas 6 000 F encaissés, ni 6 000 F encore dus.

    L'attendu ne retient que ce qui est encore demandé EN ARGENT : les deux
    lignes déposées en sortent, des deux côtés du taux à la fois.
    """
    document = await _point(caisse, CAT_RAMES)

    assert document.depots_en_nature == 2
    assert document.total_en_argent == Decimal("3000")
    assert document.total_attendu == Decimal("3000")
    assert document.total_restant_du == Decimal("0")
