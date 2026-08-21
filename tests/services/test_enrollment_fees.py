"""Un tarif par catégorie de frais — sur une vraie base, avec de vraies requêtes.

L'école qui possède déjà sa grille et ajoute le tarif affecté de la Scolarité
T1 fait exactement le geste que la fonctionnalité existe pour permettre. Tant
que la résolution retenait le tarif général ET le tarif affecté, chaque élève
affecté inscrit ensuite recevait deux lignes T1 : dette doublée, échéancier
doublé, et certificat de scolarité retenu pour un impayé qui n'existe pas.

Les tests tournent sur SQLite, via le module standard : ils exécutent le vrai
SQL du service, avec les colonnes générées qui portent la contrainte
d'unicité, sans dépendance supplémentaire ni base MySQL à provisionner.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import Class
from app.models.enrollment import AssignmentStatus
from app.models.fee import EnrollmentFee, FeeAssignmentScope, FeeCategory, FeeVariant
from app.services import enrollment_fees

AY = 2026
LEVEL_6E = 10
LEVEL_TLE = 20
SERIE_D = 30

CLASSE_6E_A = 1  # collège : aucune série
CLASSE_TLE_D = 2  # lycée : série D

CAT_SCOLARITE_T1 = 100
CAT_INSCRIPTION = 101
CAT_COGES = 102

INSCRIPTION_AFFECTE = 42


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session SQLAlchemy synchrone.

    Le service n'utilise que ces quatre gestes ; les envelopper évite d'ajouter
    un pilote asynchrone à la seule fin de faire tourner des tests.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)


def _tarif(
    variant_id: int,
    category_id: int,
    amount: str,
    *,
    level_id: int | None = LEVEL_6E,
    series_id: int | None = None,
    scope: FeeAssignmentScope | None = None,
) -> FeeVariant:
    return FeeVariant(
        id=variant_id,
        fee_category_id=category_id,
        academic_year_id=AY,
        amount=Decimal(amount),
        level_id=level_id,
        series_id=series_id,
        assignment_scope=scope,
    )


def _sqlite_schema() -> list[Table]:
    """Le schéma des quatre tables utiles, transposé pour SQLite.

    SQLite ne numérote automatiquement que les colonnes déclarées
    « INTEGER PRIMARY KEY » : les `BIGINT` du modèle refuseraient tout INSERT
    sans identifiant. On travaille sur une copie du schéma, jamais sur les
    tables du modèle, que les autres tests lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in ("classes", "fee_categories", "fee_variants", "enrollment_fees"):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve par test, avec les classes et les catégories de frais."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Class(id=CLASSE_6E_A, name="6eme A", level_id=LEVEL_6E, series_id=None),
                Class(id=CLASSE_TLE_D, name="Tle D", level_id=LEVEL_TLE, series_id=SERIE_D),
                FeeCategory(id=CAT_SCOLARITE_T1, name="Scolarite T1", is_mandatory=True),
                FeeCategory(id=CAT_INSCRIPTION, name="Inscription", is_mandatory=True),
                FeeCategory(id=CAT_COGES, name="COGES", is_mandatory=False),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _lignes_facturees(bridge: _AsyncBridge) -> list[tuple[int, Decimal]]:
    """Ce que la famille verra sur sa facture : une catégorie, un montant."""
    session = bridge._session
    rows = (
        session.query(FeeVariant.fee_category_id, EnrollmentFee.amount)
        .join(EnrollmentFee, EnrollmentFee.fee_variant_id == FeeVariant.id)
        .filter(EnrollmentFee.enrollment_id == INSCRIPTION_AFFECTE)
        .all()
    )
    return sorted((int(cat), Decimal(str(montant))) for cat, montant in rows)


async def _facturer(bridge: _AsyncBridge, statut: object, classe: int = CLASSE_6E_A) -> None:
    await enrollment_fees.create_mandatory_enrollment_fees(
        bridge,  # type: ignore[arg-type]
        INSCRIPTION_AFFECTE,
        classe,
        AY,
        statut,
    )


# ---------------------------------------------------------------------------
# Le défaut corrigé
# ---------------------------------------------------------------------------


async def test_un_tarif_general_et_un_tarif_affecte_ne_font_qu_une_ligne(
    db: _AsyncBridge,
) -> None:
    """Le cœur du défaut : deux tarifs coexistent légitimement en base, mais
    l'élève ne doit la Scolarité T1 qu'une seule fois."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    await db.flush()

    await _facturer(db, AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("20000"))]


async def test_l_eleve_non_affecte_recoit_le_tarif_non_affecte(db: _AsyncBridge) -> None:
    """Sa famille n'est pas subventionnée : lui appliquer le tarif affecté
    ferait perdre à l'école la différence sur chaque inscription."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    db.add(_tarif(3, CAT_SCOLARITE_T1, "60000", scope=FeeAssignmentScope.NON_AFFECTE))
    await db.flush()

    await _facturer(db, AssignmentStatus.NON_AFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("60000"))]


async def test_une_categorie_sans_tarif_scope_garde_le_tarif_general(db: _AsyncBridge) -> None:
    """Une école qui n'a scopé que la Scolarité continue de facturer
    l'Inscription à tout le monde au même prix."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    db.add(_tarif(3, CAT_INSCRIPTION, "25000"))
    await db.flush()

    await _facturer(db, AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == [
        (CAT_SCOLARITE_T1, Decimal("20000")),
        (CAT_INSCRIPTION, Decimal("25000")),
    ]


async def test_le_reaffecte_paie_comme_un_affecte(db: _AsyncBridge) -> None:
    """L'État le prend en charge : le tarif plein serait une erreur de caisse."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    await db.flush()

    await _facturer(db, AssignmentStatus.REAFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("20000"))]


async def test_une_inscription_sans_statut_reste_au_tarif_general(db: _AsyncBridge) -> None:
    """Choisir pour l'école entre deux montants serait pire que ne rien
    choisir : la famille le découvrirait sur sa facture."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    await db.flush()

    await _facturer(db, None)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


# ---------------------------------------------------------------------------
# Série : même règle, autre dimension
# ---------------------------------------------------------------------------


async def test_le_tarif_de_serie_l_emporte_sur_le_tarif_de_niveau(db: _AsyncBridge) -> None:
    """Une Terminale D dont le tarif de série est renseigné ne doit pas
    recevoir en plus le tarif commun à tout le niveau."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "80000", level_id=LEVEL_TLE))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "95000", level_id=LEVEL_TLE, series_id=SERIE_D))
    await db.flush()

    await _facturer(db, AssignmentStatus.NON_AFFECTE, classe=CLASSE_TLE_D)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("95000"))]


async def test_une_classe_sans_serie_ignore_les_tarifs_de_serie(db: _AsyncBridge) -> None:
    """Au collège la série est toujours vide : un tarif de série D n'a rien à
    y faire."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "95000", series_id=SERIE_D))
    await db.flush()

    await _facturer(db, AssignmentStatus.NON_AFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


# ---------------------------------------------------------------------------
# Portée du calcul
# ---------------------------------------------------------------------------


async def test_les_frais_optionnels_ne_sont_pas_factures_d_office(db: _AsyncBridge) -> None:
    """La cantine se souscrit, elle ne s'impose pas."""
    db.add(_tarif(1, CAT_COGES, "10000"))
    await db.flush()

    await _facturer(db, AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == []


async def test_refacturer_la_meme_inscription_n_ajoute_rien(db: _AsyncBridge) -> None:
    """La génération est rejouée à chaque régénération de frais : elle ne doit
    pas empiler une seconde dette."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_INSCRIPTION, "25000"))
    await db.flush()

    await _facturer(db, AssignmentStatus.NON_AFFECTE)
    await _facturer(db, AssignmentStatus.NON_AFFECTE)

    assert _lignes_facturees(db) == [
        (CAT_SCOLARITE_T1, Decimal("50000")),
        (CAT_INSCRIPTION, Decimal("25000")),
    ]


async def test_un_frais_general_deja_paye_n_est_pas_double_par_le_tarif_affecte(
    db: _AsyncBridge,
) -> None:
    """Cas de la régénération : la ligne générale est conservée parce qu'un
    versement y est imputé. Ajouter par-dessus la ligne affectée referait
    exactement le doublon que l'on corrige — le garde porte donc sur la
    catégorie, pas sur l'identifiant du tarif."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    await db.flush()
    await _facturer(db, None)

    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    await db.flush()
    await _facturer(db, AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


async def test_aucun_tarif_configure_ne_facture_rien(db: _AsyncBridge) -> None:
    """Une grille vide ne doit pas produire de dette fantôme."""
    await _facturer(db, AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == []


# ---------------------------------------------------------------------------
# L'invariant, porté par la base et non plus par une seule fonction
# ---------------------------------------------------------------------------


async def test_la_base_refuse_une_seconde_ligne_pour_la_meme_categorie(
    db: _AsyncBridge,
) -> None:
    """« Une catégorie, une ligne » ne vivait que dans une fonction Python, et
    il existe deux chemins d'insertion. Le second — le `fee_variant_id` passé
    à la création d'une inscription — ne passait par aucun garde.

    La base tranche désormais : la dette d'une famille ne peut plus doubler
    parce qu'un chemin d'écriture a oublié de vérifier."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    await db.flush()

    await _facturer(db, None)

    db.add(
        EnrollmentFee(
            id=999,
            enrollment_id=INSCRIPTION_AFFECTE,
            fee_variant_id=2,
            fee_category_id=CAT_SCOLARITE_T1,
            amount=Decimal("20000"),
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()

    db._session.rollback()


async def test_deux_categories_differentes_cohabitent_sans_heurt(db: _AsyncBridge) -> None:
    """La contrainte porte sur la catégorie, pas sur l'inscription : un élève
    doit bien l'Inscription ET la Scolarité."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_INSCRIPTION, "25000"))
    await db.flush()

    await _facturer(db, None)

    assert _lignes_facturees(db) == [
        (CAT_SCOLARITE_T1, Decimal("50000")),
        (CAT_INSCRIPTION, Decimal("25000")),
    ]


def test_la_contrainte_est_declaree_sur_la_table() -> None:
    """Elle doit exister dans le schéma que les migrations posent, pas
    seulement dans la tête de celui qui a écrit la fonction."""
    contraintes = {
        tuple(c.name for c in contrainte.columns)
        for contrainte in EnrollmentFee.__table__.constraints
        if isinstance(contrainte, UniqueConstraint)
    }
    assert ("enrollment_id", "fee_category_id") in contraintes


# ---------------------------------------------------------------------------
# La résolution, isolée
# ---------------------------------------------------------------------------


def test_la_resolution_garde_le_plus_specifique_par_categorie() -> None:
    general = _tarif(1, CAT_SCOLARITE_T1, "50000")
    affecte = _tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE)
    inscription = _tarif(3, CAT_INSCRIPTION, "25000")

    retenus = enrollment_fees.most_specific_variant_per_category([general, affecte, inscription])

    assert {v.id for v in retenus} == {affecte.id, inscription.id}


def test_l_ordre_de_lecture_ne_change_pas_le_tarif_retenu() -> None:
    """Le tri des lignes en base ne doit pas décider du montant facturé."""
    general = _tarif(1, CAT_SCOLARITE_T1, "50000")
    affecte = _tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE)

    for ordre in ([general, affecte], [affecte, general]):
        retenus = enrollment_fees.most_specific_variant_per_category(ordre)
        assert [v.id for v in retenus] == [affecte.id]
