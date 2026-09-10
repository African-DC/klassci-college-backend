"""La vue d'ensemble, mesurée en interrogeant une vraie base.

Le point par catégorie a désormais son filet (`tests/test_fee_category_ledger.py`)
et celui-ci en est le pendant, pour la question posée AVANT d'avoir choisi une
catégorie : lequel de ces frais rentre mal.

Trois propriétés y sont tenues, et ce sont celles qui rendent la vue d'ensemble
utilisable :

- **la carte annonce le total du document qu'elle ouvre** — un taux de carte
  calculé à part finirait par contredire le point, et c'est un écart qu'on ne
  remarque qu'une fois le chiffre envoyé à un prestataire ;
- **ce qui est entré se cloisonne, ce qui reste dû ne se cloisonne pas** — la
  caissière lit son encaissement par catégorie, et ni l'attendu, ni le taux,
  ni les compteurs, qui se lisent sur tout l'argent reçu ;
- **la lecture est groupée** — le nombre de requêtes ne dépend pas du nombre de
  catégories. Une par catégorie ferait relire la même table autant de fois
  qu'il y a de frais, sur un écran qui s'ouvre à chaque consultation.

Comme le fichier voisin, la fixture a la forme que la caisse produit depuis la
migration 0028 : le versement n'existe QUE par son allocation.
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, create_engine, delete, update
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
from app.services import fee_category_ledger, fee_category_overview

ANNEE = 1
CLASSE_A = 1
CLASSE_B = 2

INSCRIPTION = 5
CANTINE = 6
RAMES = 7

AYA, BAKARY, CYRILLE, DJENEBA, EMERAUDE = 1, 2, 3, 4, 5
INSC_AYA, INSC_BAKARY, INSC_CYRILLE, INSC_DJENEBA, INSC_ANNULEE = 10, 11, 12, 13, 14

# Les lignes de frais, nommées « <catégorie>_<élève> ».
INS_AYA, INS_BAKARY, INS_DJENEBA = 100, 101, 103
CAN_AYA, CAN_BAKARY = 110, 111
RAM_AYA, RAM_BAKARY, RAM_CYRILLE, RAM_DJENEBA = 120, 121, 122, 123

CAISSE_SOPHIE = 21
CAISSE_MARCEL = 22

OCTOBRE = datetime(2026, 10, 5, 9, 30)
NOVEMBRE = datetime(2026, 11, 5, 11, 0)
DEBUT_NOVEMBRE = datetime(2026, 11, 1)


class _Pont:
    """Donne l'allure d'une `AsyncSession` à une session synchrone, et compte.

    Le service n'utilise que `execute`. Les compter est le seul moyen honnête
    de tenir la promesse « une lecture groupée, pas une par catégorie » : elle
    ne se vérifie pas en relisant le texte du programme, qui pourrait changer
    de forme sans changer de coût.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.lectures = 0

    async def execute(self, statement: object) -> object:
        self.lectures += 1
        return self._session.execute(statement)  # type: ignore[arg-type]


def _eleve(ident: int, nom: str, prenom: str, matricule: str) -> Student:
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
    categorie: int,
    montant: str,
    statut: str = EnrollmentFeeStatus.PENDING.value,
    *,
    depose_le: datetime | None = None,
    depose_par: int | None = None,
) -> EnrollmentFee:
    return EnrollmentFee(
        id=ident,
        enrollment_id=inscription,
        fee_variant_id=categorie,
        fee_category_id=categorie,
        amount=Decimal(montant),
        status=statut,
        deposited_at=depose_le,
        deposited_by_user_id=depose_par,
    )


def _versement(
    ident: int,
    inscription: int,
    montant: str,
    statut: str,
    caisse: int,
    quand: datetime,
) -> Payment:
    """Un versement tel que la caisse le produit depuis 0028."""
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
    """Trois catégories, quatre inscriptions ouvertes, deux caisses.

    Chaque catégorie a sa forme : l'Inscription rentre à moitié, la Cantine ne
    rentre pas du tout, les Rames mêlent un dépôt, une exonération et deux
    impayés. Cyrille n'est facturé ni pour l'Inscription ni pour la Cantine :
    c'est l'élève sans ligne, qui faisait rétrécir le dénominateur en silence.
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
                _eleve(AYA, "KOUASSI", "Aya", "C-2026-001"),
                _eleve(BAKARY, "TRAORÉ", "Bakary", "C-2026-002"),
                _eleve(CYRILLE, "N'GUESSAN", "Cyrille", "C-2026-003"),
                _eleve(DJENEBA, "OUATTARA", "Djeneba", "C-2026-004"),
                _eleve(EMERAUDE, "ZADI", "Emeraude", "C-2026-005"),
                _inscription(INSC_AYA, AYA, CLASSE_A),
                _inscription(INSC_BAKARY, BAKARY, CLASSE_A),
                _inscription(INSC_CYRILLE, CYRILLE, CLASSE_A),
                _inscription(INSC_DJENEBA, DJENEBA, CLASSE_B),
                _inscription(
                    INSC_ANNULEE,
                    EMERAUDE,
                    CLASSE_A,
                    statut=EnrollmentStatus.ANNULE.value,
                ),
                # Les priorites sont celles de la convention d'imputation :
                # l'Inscription d'abord, le reste ensuite.
                FeeCategory(id=INSCRIPTION, name="Inscription", priority=10, is_mandatory=True),
                FeeCategory(id=CANTINE, name="Cantine", priority=50, is_mandatory=False),
                FeeCategory(
                    id=RAMES,
                    name="Paquet de rames",
                    priority=90,
                    is_mandatory=False,
                    accepts_in_kind=True,
                ),
                FeeVariant(
                    id=INSCRIPTION,
                    fee_category_id=INSCRIPTION,
                    academic_year_id=ANNEE,
                    amount=Decimal("25000"),
                ),
                FeeVariant(
                    id=CANTINE,
                    fee_category_id=CANTINE,
                    academic_year_id=ANNEE,
                    amount=Decimal("10000"),
                ),
                FeeVariant(
                    id=RAMES,
                    fee_category_id=RAMES,
                    academic_year_id=ANNEE,
                    amount=Decimal("3000"),
                ),
                # Les statuts sont ceux que `recompute_fee_status` poserait au
                # vu des versements plus bas : de ce champ, et de lui seul,
                # sortent les compteurs par seau.
                _frais(INS_AYA, INSC_AYA, INSCRIPTION, "25000", EnrollmentFeeStatus.PAID.value),
                _frais(
                    INS_BAKARY,
                    INSC_BAKARY,
                    INSCRIPTION,
                    "25000",
                    EnrollmentFeeStatus.PARTIAL.value,
                ),
                _frais(INS_DJENEBA, INSC_DJENEBA, INSCRIPTION, "25000"),
                _frais(CAN_AYA, INSC_AYA, CANTINE, "10000"),
                _frais(CAN_BAKARY, INSC_BAKARY, CANTINE, "10000"),
                # Aya a depose sa rame a la caisse de Sophie.
                _frais(
                    RAM_AYA,
                    INSC_AYA,
                    RAMES,
                    "3000",
                    EnrollmentFeeStatus.IN_KIND.value,
                    depose_le=OCTOBRE,
                    depose_par=CAISSE_SOPHIE,
                ),
                _frais(RAM_BAKARY, INSC_BAKARY, RAMES, "3000"),
                _frais(RAM_CYRILLE, INSC_CYRILLE, RAMES, "3000", EnrollmentFeeStatus.WAIVED.value),
                _frais(RAM_DJENEBA, INSC_DJENEBA, RAMES, "3000"),
            ]
        )
        s.flush()

        s.add_all(
            [
                # Sophie solde l'Inscription d'Aya en octobre.
                _versement(
                    500, INSC_AYA, "25000", PaymentStatus.COMPLETED.value, CAISSE_SOPHIE, OCTOBRE
                ),
                # Marcel encaisse en novembre un acompte de Bakary, REPARTI sur
                # deux categories : c'est le versement qui doit compter une
                # fois dans chacune, et une seule.
                _versement(
                    501, INSC_BAKARY, "4000", PaymentStatus.COMPLETED.value, CAISSE_MARCEL, NOVEMBRE
                ),
                # Saisi mais pas encaisse : cet argent n'existe pas encore.
                _versement(
                    502, INSC_DJENEBA, "3000", PaymentStatus.PENDING.value, CAISSE_SOPHIE, NOVEMBRE
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                PaymentAllocation(
                    payment_id=500, enrollment_fee_id=INS_AYA, amount=Decimal("25000")
                ),
                PaymentAllocation(
                    payment_id=501, enrollment_fee_id=INS_BAKARY, amount=Decimal("3000")
                ),
                PaymentAllocation(
                    payment_id=501, enrollment_fee_id=RAM_BAKARY, amount=Decimal("1000")
                ),
                PaymentAllocation(
                    payment_id=502, enrollment_fee_id=INS_DJENEBA, amount=Decimal("3000")
                ),
            ]
        )
        s.commit()
        yield s


def _carte(
    vue: fee_category_overview.CategoriesOverview, categorie: int
) -> fee_category_overview.LigneCategorie:
    return next(ligne for ligne in vue.categories if ligne.category_id == categorie)


# ---------------------------------------------------------------------------
# Ce que la vue additionne
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_versement_reparti_compte_une_fois_dans_chaque_categorie(db: Session) -> None:
    """Les 4 000 F de Bakary valent 3 000 sur l'Inscription et 1 000 sur les Rames.

    Sommer le versement entier — et non ses allocations — les compterait deux
    fois : 4 000 F d'un côté, 4 000 de l'autre, et la vue d'ensemble
    annoncerait 8 000 F rentrés là où la caisse en a reçu 4 000.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    assert _carte(vue, INSCRIPTION).total_en_argent == Decimal("28000")
    assert _carte(vue, RAMES).total_en_argent == Decimal("1000")


@pytest.mark.asyncio
async def test_un_versement_non_encaisse_n_entre_pas(db: Session) -> None:
    """Tant que l'argent n'est pas encaissé, il n'est pas entré.

    Les 3 000 F saisis pour Djeneba attendent leur validation : les compter
    solderait une ligne que la caisse n'a pas reçue.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    inscription = _carte(vue, INSCRIPTION)
    assert inscription.total_en_argent == Decimal("28000")
    assert inscription.eleves_en_argent == 2


@pytest.mark.asyncio
async def test_l_attendu_ecarte_l_exonere_et_le_depose(db: Session) -> None:
    """Une ligne exonérée ou déposée n'est plus due : elle sort du dénominateur.

    Sur les Rames, Aya a déposé et Cyrille est exonéré : l'école n'attend plus
    que les 3 000 F de Bakary et ceux de Djeneba. Les garder au dénominateur
    ferait paraître le frais bien pire qu'il n'est.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    assert _carte(vue, RAMES).total_attendu == Decimal("6000")
    assert _carte(vue, INSCRIPTION).total_attendu == Decimal("75000")


@pytest.mark.asyncio
async def test_le_taux_ne_depasse_pas_cent_pour_cent(db: Session) -> None:
    """Une famille qui verse puis se fait exonérer sort des DEUX côtés.

    Aya et Bakary ont versé 28 000 F sur l'Inscription, puis l'école les
    exonère. Un taux calculé « argent reçu sur attendu » vaudrait alors
    28 000 / 25 000, soit 112 % : une école qui affiche 112 % de recouvrement
    n'est pas crue sur le reste de la page. Le taux étant l'attendu moins ce
    qui reste dû, il ne peut pas déborder — il ne reste que Djeneba, qui n'a
    rien versé.
    """
    db.execute(
        update(EnrollmentFee)
        .where(EnrollmentFee.id.in_([INS_AYA, INS_BAKARY]))
        .values(status=EnrollmentFeeStatus.WAIVED.value)
    )
    db.commit()

    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    inscription = _carte(vue, INSCRIPTION)
    assert inscription.total_attendu == Decimal("25000")
    assert inscription.taux_recouvrement == 0.0


@pytest.mark.asyncio
async def test_un_frais_qui_ne_rentre_pas_affiche_zero_et_non_l_absence(db: Session) -> None:
    """Zéro pour cent est un fait ; c'est l'absence de dénominateur qui n'en est pas un.

    Personne n'a payé la Cantine : son taux vaut 0, et le dire est tout
    l'intérêt de l'écran. `None` est réservé à ce qui ne se calcule pas.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    cantine = _carte(vue, CANTINE)
    assert cantine.taux_recouvrement == 0.0
    assert cantine.total_attendu == Decimal("20000")
    assert cantine.total_restant_du == Decimal("20000")


@pytest.mark.asyncio
async def test_l_eleve_sans_ligne_est_compte_categorie_par_categorie(db: Session) -> None:
    """« Tout le monde a payé » se lisait sur une liste où les non-facturés manquaient.

    Cyrille n'est facturé ni pour l'Inscription ni pour la Cantine, et l'école
    doit le voir là où il manque — pas sur les Rames, où il a bien sa ligne.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    assert vue.effectif_perimetre == 4
    assert _carte(vue, INSCRIPTION).eleves_sans_ligne == 1
    assert _carte(vue, CANTINE).eleves_sans_ligne == 2
    assert _carte(vue, RAMES).eleves_sans_ligne == 0


@pytest.mark.asyncio
async def test_les_compteurs_couvrent_toutes_les_lignes_de_la_categorie(db: Session) -> None:
    """La somme des seaux vaut le nombre de lignes : un onglet qui ne retombe pas fait douter."""
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    rames = _carte(vue, RAMES)
    assert rames.compteurs is not None
    assert sum(rames.compteurs.values()) == rames.eleves_factures == 4
    assert rames.compteurs[EnrollmentFeeStatus.PENDING.value] == 2
    assert rames.compteurs[EnrollmentFeeStatus.WAIVED.value] == 1
    assert rames.compteurs[EnrollmentFeeStatus.IN_KIND.value] == 1


# ---------------------------------------------------------------------------
# La période borne un événement, jamais un état
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_periode_borne_l_entre_mais_ni_l_attendu_ni_le_du(db: Session) -> None:
    """« Ce qui est rentré en novembre » n'est pas « ce qui reste à rentrer ».

    Sur novembre seul, le versement d'octobre d'Aya n'entre pas — c'est un
    événement, il est hors fenêtre. Mais l'attendu et le reste dû valent à
    l'instant où on les lit : les borner ferait réapparaître une dette réglée,
    et la carte annoncerait un taux qui s'effondre chaque fois qu'on choisit
    un mois.
    """
    vue = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, date_from=DEBUT_NOVEMBRE
    )

    inscription = _carte(vue, INSCRIPTION)
    assert inscription.total_en_argent == Decimal("3000")
    assert inscription.total_attendu == Decimal("75000")
    # Aya a soldé en octobre : sa ligne ne doit rien, fenêtre ou pas.
    assert inscription.total_restant_du == Decimal("47000")


# ---------------------------------------------------------------------------
# Ce qui est entré se cloisonne ; ce qui reste dû ne se cloisonne pas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_caissiere_lit_son_encaissement_par_categorie(db: Session) -> None:
    """Son point du soir, catégorie par catégorie : c'est un fait sur sa caisse.

    Sophie n'a encaissé que l'Inscription d'Aya. Lui refuser ce chiffre
    l'empêcherait de faire son point ; lui servir celui de Marcel lui ferait
    signer un total qu'elle n'a pas en caisse.
    """
    vue = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, received_by=CAISSE_SOPHIE, consolide=False
    )

    assert _carte(vue, INSCRIPTION).total_en_argent == Decimal("25000")
    assert _carte(vue, RAMES).total_en_argent == Decimal("0")
    # L'effectif n'est pas de l'argent : elle a le droit de savoir combien
    # d'élèves son point aurait dû couvrir.
    assert vue.effectif_perimetre == 4
    assert _carte(vue, INSCRIPTION).eleves_sans_ligne == 1


@pytest.mark.asyncio
async def test_le_recouvrement_est_absent_pour_la_caissiere_jamais_a_zero(db: Session) -> None:
    """Un zéro se lirait comme un solde, et un taux d'une seule caisse comme une dette.

    Le reste dû, l'attendu, le taux et les compteurs forment un seul bloc :
    ils se lisent sur tout l'argent reçu, et sur une seule caisse ils
    annonceraient une dette chez des familles ayant payé au guichet d'à côté.
    """
    vue = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, received_by=CAISSE_SOPHIE, consolide=False
    )

    assert vue.consolide is False
    for carte in vue.categories:
        assert carte.total_attendu is None
        assert carte.taux_recouvrement is None
        assert carte.total_restant_du is None
        assert carte.eleves_restant_du is None
        assert carte.compteurs is None


@pytest.mark.asyncio
async def test_un_depot_se_cloisonne_comme_de_l_argent(db: Session) -> None:
    """Un dépôt est quelque chose qui est ENTRÉ : il suit la même règle que le versement.

    La rame d'Aya est passée par la caisse de Sophie. Marcel ne doit pas la
    compter, sinon sa carte annoncerait un stock qu'il n'a pas reçu — sous un
    écran qui affirme ne couvrir que sa caisse.
    """
    sophie = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, received_by=CAISSE_SOPHIE, consolide=False
    )
    marcel = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, received_by=CAISSE_MARCEL, consolide=False
    )

    assert _carte(sophie, RAMES).depots_en_nature == 1
    assert _carte(marcel, RAMES).depots_en_nature == 0


# ---------------------------------------------------------------------------
# La carte et le document qu'elle ouvre
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("categorie", [INSCRIPTION, CANTINE, RAMES])
async def test_la_carte_annonce_les_memes_chiffres_que_le_point(
    db: Session, categorie: int
) -> None:
    """Le taux d'une carte et celui du point sont la même addition, ou ils divergeront.

    C'est la raison d'être du partage de `fee_category_ledger.totaliser` : deux
    calculs séparés finissent toujours par répondre deux chiffres à la même
    question, et celui qu'on découvre en dernier est celui qu'on a déjà envoyé
    à un prestataire.
    """
    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)
    point = await fee_category_ledger.load_category_ledger(
        _Pont(db), category_id=categorie, academic_year_id=ANNEE
    )
    carte = _carte(vue, categorie)

    assert carte.total_en_argent == point.total_en_argent
    assert carte.total_attendu == point.total_attendu
    assert carte.total_restant_du == point.total_restant_du
    assert carte.taux_recouvrement == point.taux_recouvrement
    assert carte.compteurs == point.compteurs
    assert carte.depots_en_nature == point.depots_en_nature
    assert carte.eleves_sans_ligne == point.eleves_sans_ligne


# ---------------------------------------------------------------------------
# Ce que la vue montre, et dans quel ordre
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_une_categorie_sans_ligne_sur_le_perimetre_n_apparait_pas(db: Session) -> None:
    """« Personne n'a payé » et « personne n'a été facturé » appellent deux gestes.

    Une catégorie qu'aucune ligne ne porte n'est pas un frais qui rentre mal :
    c'est un frais qui n'a pas été posé, et l'outil qui répond à celui-là
    compte les lignes manquantes d'un tarif. La faire figurer ici avec un taux
    de 0 % enverrait relancer des familles qu'on n'a jamais facturées.
    """
    db.execute(delete(PaymentAllocation).where(PaymentAllocation.enrollment_fee_id == RAM_BAKARY))
    db.execute(delete(EnrollmentFee).where(EnrollmentFee.fee_category_id == RAMES))
    db.commit()

    vue = await fee_category_overview.load_categories_overview(_Pont(db), academic_year_id=ANNEE)

    assert [carte.category_id for carte in vue.categories] == [INSCRIPTION, CANTINE]


@pytest.mark.asyncio
async def test_l_ordre_suit_la_convention_de_l_ecole_et_non_le_taux(db: Session) -> None:
    """L'ordre des cartes ne doit pas dépendre des droits du lecteur.

    Les Rames rentrent plus mal que l'Inscription ; trier par taux les
    mettrait en tête pour le comptable et nulle part pour la caissière, qui
    n'a pas de taux. Deux personnes décrivant leur écran au téléphone ne
    verraient pas la même chose au même endroit. L'ordre est donc celui que
    l'école a configuré, et le tri par ce qui va mal se fait à l'écran.
    """
    comptable = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE
    )
    caissiere = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, received_by=CAISSE_SOPHIE, consolide=False
    )

    attendu = [INSCRIPTION, CANTINE, RAMES]
    assert [carte.category_id for carte in comptable.categories] == attendu
    assert [carte.category_id for carte in caissiere.categories] == attendu
    # Le frais qui rentre le plus mal n'est pas en tete : c'est bien la
    # convention de l'ecole qui ordonne, pas le taux.
    assert _carte(comptable, RAMES).taux_recouvrement is not None
    assert (
        _carte(comptable, RAMES).taux_recouvrement
        < _carte(comptable, INSCRIPTION).taux_recouvrement
    )


@pytest.mark.asyncio
async def test_une_classe_nommee_meme_quand_elle_n_a_aucune_ligne(db: Session) -> None:
    """Le périmètre se nomme depuis le critère, jamais depuis les lignes rendues.

    Une classe dont aucune ligne ne sort a quand même un nom, et c'est
    précisément le moment où l'écran doit le dire : sans lui, on lirait le
    document comme celui de toute l'école.
    """
    db.execute(delete(PaymentAllocation))
    db.execute(delete(EnrollmentFee))
    db.commit()

    vue = await fee_category_overview.load_categories_overview(
        _Pont(db), academic_year_id=ANNEE, class_id=CLASSE_B
    )

    assert vue.class_name == "6eme B"
    assert vue.categories == ()
    assert vue.effectif_perimetre == 1


# ---------------------------------------------------------------------------
# Le coût de la lecture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_lecture_ne_grossit_pas_avec_le_nombre_de_categories(db: Session) -> None:
    """Une lecture groupée, pas un point chargé par frais.

    C'est la propriété qui rend l'écran ouvrable : une école a huit ou dix
    catégories, et une requête par catégorie ferait dix relectures de la même
    table à chaque consultation. On la mesure en comptant les lectures sur
    trois catégories, puis sur deux : le compte doit être le même.
    """
    trois = _Pont(db)
    await fee_category_overview.load_categories_overview(trois, academic_year_id=ANNEE)

    db.execute(delete(PaymentAllocation).where(PaymentAllocation.enrollment_fee_id == RAM_BAKARY))
    db.execute(delete(EnrollmentFee).where(EnrollmentFee.fee_category_id == RAMES))
    db.commit()

    deux = _Pont(db)
    vue = await fee_category_overview.load_categories_overview(deux, academic_year_id=ANNEE)

    assert len(vue.categories) == 2
    assert trois.lectures == deux.lectures
