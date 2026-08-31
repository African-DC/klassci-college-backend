"""Les frais d'entrée : ce qu'un nouvel élève paie, ce qu'un ancien ne repaie pas.

Le collège Rostan facture une chemise cartonnée à ses arrivants. Tant que la
grille ne connaissait qu'un montant par niveau, il fallait la saisir à la main
sur chaque dossier, ou la faire payer à tout le monde.

Le piège est ailleurs, et c'est lui que ces tests gardent : **l'établissement
dont les années passées ne sont pas reconstituées ne sait pas qui est
nouveau**. Une inscription dont le profil n'est pas tranché ne doit alors
recevoir AUCUN tarif à profil, ni « nouveau » ni « ancien ». Déduire « aucune
inscription antérieure, donc nouveau » facturerait la chemise à tous les
anciens élèves de l'école, et la famille le découvrirait sur sa facture.

Les tests tournent sur SQLite, via le module standard : ils exécutent le vrai
SQL du service, avec les colonnes générées qui portent la contrainte
d'unicité, sans base MySQL à provisionner.
"""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, UniqueConstraint, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import BusinessValidationError
from app.models.academic import Class
from app.models.enrollment import AssignmentStatus, Enrollment
from app.models.fee import (
    EnrollmentFee,
    FeeAssignmentScope,
    FeeCategory,
    FeeEnrollmentProfile,
    FeeVariant,
)
from app.services import enrollment_fees

AY = 2026
LEVEL_6E = 10
LEVEL_TLE = 20
SERIE_D = 30

CLASSE_6E_A = 1  # collège : aucune série
CLASSE_TLE_D = 2  # lycée : série D

CAT_SCOLARITE_T1 = 100
CAT_CHEMISE = 101

INSCRIPTION = 42


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
    profil: FeeEnrollmentProfile | None = None,
) -> FeeVariant:
    return FeeVariant(
        id=variant_id,
        fee_category_id=category_id,
        academic_year_id=AY,
        amount=Decimal(amount),
        level_id=level_id,
        series_id=series_id,
        assignment_scope=scope,
        enrollment_profile=profil,
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
                FeeCategory(id=CAT_CHEMISE, name="Chemise cartonnee", is_mandatory=True),
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
        .filter(EnrollmentFee.enrollment_id == INSCRIPTION)
        .all()
    )
    return sorted((int(cat), Decimal(str(montant))) for cat, montant in rows)


async def _facturer(
    bridge: _AsyncBridge,
    *,
    profil: bool | None,
    statut: object = AssignmentStatus.NON_AFFECTE,
    classe: int = CLASSE_6E_A,
) -> None:
    await enrollment_fees.create_mandatory_enrollment_fees(
        bridge,  # type: ignore[arg-type]
        INSCRIPTION,
        classe,
        AY,
        statut,
        profil,
    )


# ---------------------------------------------------------------------------
# L'invariant central : on ne tranche pas à la place de l'école
# ---------------------------------------------------------------------------


async def test_une_inscription_sans_profil_ne_recoit_aucun_tarif_a_profil(
    db: _AsyncBridge,
) -> None:
    """Le cas Rostan. L'année précédente n'est pas en base, le profil est vide,
    et la chemise n'a de tarif que pour les nouveaux : personne ne la reçoit
    tant que quelqu'un n'a pas coché."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=None)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


async def test_une_inscription_sans_profil_garde_le_tarif_general(db: _AsyncBridge) -> None:
    """Elle ne reçoit ni le tarif « nouveau » ni le tarif « ancien » : choisir
    pour l'école entre deux montants serait pire que ne rien choisir."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    db.add(_tarif(3, CAT_SCOLARITE_T1, "48000", profil=FeeEnrollmentProfile.ANCIEN))
    await db.flush()

    await _facturer(db, profil=None)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


def test_les_cles_de_profil_copient_celles_de_la_portee() -> None:
    """La règle est la même que pour l'affectation, et elle doit le rester :
    un profil vide ouvre à la seule sentinelle, un profil connu ouvre à deux."""
    assert enrollment_fees.applicable_profile_keys(None) == ("",)
    assert enrollment_fees.applicable_profile_keys(True) == ("", "nouveau")
    assert enrollment_fees.applicable_profile_keys(False) == ("", "ancien")


# ---------------------------------------------------------------------------
# Nouveau, ancien : ce que chacun reçoit
# ---------------------------------------------------------------------------


async def test_le_nouvel_eleve_recoit_le_tarif_nouveau(db: _AsyncBridge) -> None:
    """C'est le geste que la fonctionnalité existe pour permettre."""
    db.add(_tarif(1, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=True)

    assert _lignes_facturees(db) == [(CAT_CHEMISE, Decimal("3000"))]


async def test_l_ancien_ne_recoit_rien_quand_la_categorie_n_a_que_le_tarif_nouveau(
    db: _AsyncBridge,
) -> None:
    """La chemise cartonnée se paie une fois, à l'entrée. La refacturer chaque
    année à une famille fidèle est exactement ce qu'on évite ici."""
    db.add(_tarif(1, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=False)

    assert _lignes_facturees(db) == []


async def test_un_tarif_nouveau_plus_cher_l_emporte_sur_la_grille_generale(
    db: _AsyncBridge,
) -> None:
    """Le tarif le plus spécifique gagne, pas le moins cher : une école qui
    ajoute un droit d'entrée majoré doit le voir appliqué."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=True)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("65000"))]


async def test_l_ancien_garde_la_grille_generale_devant_le_tarif_nouveau(
    db: _AsyncBridge,
) -> None:
    """Le pendant du test précédent : la majoration ne doit atteindre que les
    arrivants, sinon toute l'école paie l'entrée deux fois."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=False)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


async def test_une_seule_ligne_par_categorie_malgre_le_tarif_a_profil(db: _AsyncBridge) -> None:
    """Deux tarifs coexistent légitimement en base ; la dette, elle, est une."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=True)

    assert len(_lignes_facturees(db)) == 1


# ---------------------------------------------------------------------------
# Trois dimensions : qui l'emporte sur qui
# ---------------------------------------------------------------------------


async def test_la_portee_d_affectation_l_emporte_sur_le_profil(db: _AsyncBridge) -> None:
    """Un affecté est subventionné par l'État : lui facturer le plein tarif
    parce qu'il est aussi nouveau est l'erreur la plus coûteuse des trois, et
    celle qu'on rattrape le moins bien une fois la facture partie."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "20000", scope=FeeAssignmentScope.AFFECTE))
    db.add(_tarif(3, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await _facturer(db, profil=True, statut=AssignmentStatus.AFFECTE)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("20000"))]


async def test_le_profil_l_emporte_sur_la_serie(db: _AsyncBridge) -> None:
    """Le profil est une décision prise sur cet élève-là ; la série est une
    propriété de sa classe, déjà largement impliquée par le niveau exigé."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "80000", level_id=LEVEL_TLE))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "95000", level_id=LEVEL_TLE, series_id=SERIE_D))
    db.add(
        _tarif(
            3,
            CAT_SCOLARITE_T1,
            "88000",
            level_id=LEVEL_TLE,
            profil=FeeEnrollmentProfile.NOUVEAU,
        )
    )
    await db.flush()

    await _facturer(db, profil=True, classe=CLASSE_TLE_D)

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("88000"))]


async def test_l_ordre_de_lecture_ne_change_pas_le_tarif_retenu() -> None:
    """Le tri des lignes en base ne doit pas décider du montant facturé."""
    general = _tarif(1, CAT_SCOLARITE_T1, "50000")
    nouveau = _tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU)

    for ordre in ([general, nouveau], [nouveau, general]):
        retenus = enrollment_fees.most_specific_variant_per_category(ordre)
        assert [v.id for v in retenus] == [nouveau.id]


# ---------------------------------------------------------------------------
# Le tarif nommé au guichet : l'autre chemin d'écriture
# ---------------------------------------------------------------------------


def _inscription(*, profil: bool | None) -> Enrollment:
    """Une inscription tenue en mémoire : le garde n'en lit que les dimensions."""
    return Enrollment(id=INSCRIPTION, class_id=CLASSE_6E_A, is_new_student=profil)


async def test_un_tarif_a_profil_est_refuse_sur_une_inscription_non_tranchee(
    db: _AsyncBridge,
) -> None:
    """La porte de sortie de l'invariant, celle par laquelle un corps de
    requête posait un montant que le chemin normal refuse. Le refus est
    explicite : ignorer le tarif en silence laisserait le guichet croire la
    ligne posée."""
    db.add(_tarif(1, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    with pytest.raises(BusinessValidationError):
        await enrollment_fees.create_explicit_enrollment_fee(
            db,  # type: ignore[arg-type]
            enrollment=_inscription(profil=None),
            fee_variant_id=1,
        )

    assert _lignes_facturees(db) == []


async def test_un_tarif_a_profil_est_refuse_sur_le_profil_oppose(db: _AsyncBridge) -> None:
    """Un ancien ne se voit pas poser le droit d'entrée des nouveaux, quel que
    soit le chemin emprunté pour l'écrire."""
    db.add(_tarif(1, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    with pytest.raises(BusinessValidationError):
        await enrollment_fees.create_explicit_enrollment_fee(
            db,  # type: ignore[arg-type]
            enrollment=_inscription(profil=False),
            fee_variant_id=1,
        )


async def test_le_tarif_nomme_passe_quand_il_vise_bien_cette_inscription(
    db: _AsyncBridge,
) -> None:
    """Le garde ne doit pas fermer plus que la porte : le geste légitime,
    celui pour lequel ce chemin existe, continue de passer."""
    db.add(_tarif(1, CAT_CHEMISE, "3000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    await enrollment_fees.create_explicit_enrollment_fee(
        db,  # type: ignore[arg-type]
        enrollment=_inscription(profil=True),
        fee_variant_id=1,
    )

    assert _lignes_facturees(db) == [(CAT_CHEMISE, Decimal("3000"))]


async def test_un_tarif_sans_profil_passe_sur_une_inscription_non_tranchee(
    db: _AsyncBridge,
) -> None:
    """La grille générale s'applique à tout le monde : elle n'a jamais eu
    besoin qu'on tranche."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    await db.flush()

    await enrollment_fees.create_explicit_enrollment_fee(
        db,  # type: ignore[arg-type]
        enrollment=_inscription(profil=None),
        fee_variant_id=1,
    )

    assert _lignes_facturees(db) == [(CAT_SCOLARITE_T1, Decimal("50000"))]


# ---------------------------------------------------------------------------
# L'unicité, portée par la base
# ---------------------------------------------------------------------------


async def test_la_base_refuse_deux_tarifs_qui_ne_different_que_par_un_profil_nul(
    db: _AsyncBridge,
) -> None:
    """`NULL` n'étant jamais égal à `NULL`, une contrainte posée directement sur
    `enrollment_profile` ne se déclencherait jamais — et l'école se retrouverait
    avec deux montants pour la même case, dont l'affichage en retiendrait un au
    hasard. C'est la colonne générée qui rend la contrainte effective."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    await db.flush()

    db.add(_tarif(2, CAT_SCOLARITE_T1, "51000"))
    with pytest.raises(IntegrityError):
        await db.flush()

    db._session.rollback()


async def test_un_tarif_a_profil_cohabite_avec_le_tarif_general(db: _AsyncBridge) -> None:
    """Sans quoi l'école ne pourrait pas poser un droit d'entrée par-dessus sa
    grille, ce qui est exactement le but."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "50000"))
    db.add(_tarif(2, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    db.add(_tarif(3, CAT_SCOLARITE_T1, "48000", profil=FeeEnrollmentProfile.ANCIEN))
    await db.flush()

    assert db._session.query(FeeVariant).count() == 3


async def test_deux_tarifs_du_meme_profil_se_heurtent(db: _AsyncBridge) -> None:
    """La nouvelle dimension entre dans la clé, elle ne la remplace pas."""
    db.add(_tarif(1, CAT_SCOLARITE_T1, "65000", profil=FeeEnrollmentProfile.NOUVEAU))
    await db.flush()

    db.add(_tarif(2, CAT_SCOLARITE_T1, "66000", profil=FeeEnrollmentProfile.NOUVEAU))
    with pytest.raises(IntegrityError):
        await db.flush()

    db._session.rollback()


def test_la_contrainte_porte_bien_les_six_dimensions() -> None:
    """Elle doit exister dans le schéma que les migrations posent, pas
    seulement dans la tête de celui qui a écrit la fonction."""
    contraintes = {
        tuple(c.name for c in contrainte.columns)
        for contrainte in FeeVariant.__table__.constraints
        if isinstance(contrainte, UniqueConstraint)
    }
    assert (
        "fee_category_id",
        "academic_year_id",
        "level_key",
        "series_key",
        "scope_key",
        "profile_key",
    ) in contraintes
