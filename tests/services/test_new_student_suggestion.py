"""« Cet élève est-il nouveau ? » — et le droit de répondre « je ne sais pas ».

La secrétaire coche une case, et cette case décide d'un montant. Le serveur
peut l'aider en lisant l'historique, mais il y a un cas où il doit se taire :
quand l'établissement n'a aucune inscription des années précédentes en base.
Le collège Rostan est dans ce cas — l'année 2025-2026 n'est pas reconstituée.
Répondre « aucune inscription antérieure, donc nouveau » y facturerait les
frais d'entrée à tous les anciens élèves.

C'est la règle que le rapport approfondi tenait déjà pour sa colonne
Red / Non Red, avec le même critère et les mêmes statuts. Elle vit désormais
dans un seul module, et ces tests couvrent les deux usages.

Les tests tournent sur SQLite, via le module standard : ils exécutent le vrai
SQL du service, jointures comprises, sans base MySQL à provisionner.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.services import enrollment_history

AY_COURANTE = 2026
AY_PRECEDENTE = 2025

LEVEL_6E = 10
LEVEL_5E = 11
CLASSE_6E_A = 1
CLASSE_5E_A = 2

FIDELE = 100  # inscrit l'an dernier
ARRIVANT = 101  # jamais vu ici


class _AsyncBridge:
    """L'allure d'une `AsyncSession` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: object) -> object:
        return self.session.execute(statement)  # type: ignore[arg-type]


def _sqlite_schema() -> list[Table]:
    """Le schéma des trois tables utiles, transposé pour SQLite.

    SQLite ne numérote automatiquement que les colonnes déclarées
    « INTEGER PRIMARY KEY » : les `BIGINT` du modèle refuseraient tout INSERT
    sans identifiant. On travaille sur une copie du schéma, jamais sur les
    tables du modèle, que les autres tests lisent.
    """
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    utiles = []
    for nom in ("academic_years", "classes", "enrollments"):
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        utiles.append(table)
    return utiles


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    """Une base neuve par test : deux années, deux classes, aucune inscription."""
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                AcademicYear(
                    id=AY_PRECEDENTE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                ),
                AcademicYear(
                    id=AY_COURANTE,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                ),
                Class(id=CLASSE_6E_A, name="6eme A", level_id=LEVEL_6E),
                Class(id=CLASSE_5E_A, name="5eme A", level_id=LEVEL_5E),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _inscrire(
    db: _AsyncBridge,
    enrollment_id: int,
    student_id: int,
    *,
    annee: int = AY_PRECEDENTE,
    classe: int = CLASSE_6E_A,
    statut: EnrollmentStatus = EnrollmentStatus.VALIDE,
) -> None:
    db.session.add(
        Enrollment(
            id=enrollment_id,
            student_id=student_id,
            class_id=classe,
            academic_year_id=annee,
            status=statut,
        )
    )
    db.session.flush()


async def _suggestion(db: _AsyncBridge, student_id: int) -> tuple[bool | None, str]:
    return await enrollment_history.suggest_new_student(
        db,  # type: ignore[arg-type]
        student_id,
        AY_COURANTE,
    )


# ---------------------------------------------------------------------------
# Le piège : une école sans passé en base
# ---------------------------------------------------------------------------


async def test_rend_null_quand_aucune_annee_anterieure_n_est_renseignee(
    db: _AsyncBridge,
) -> None:
    """Le cas Rostan. Rien en base avant cette année : le serveur ne tranche
    pas, et la phrase le dit à la secrétaire au lieu de la laisser deviner."""
    suggested, reason = await _suggestion(db, ARRIVANT)

    assert suggested is None
    assert reason


async def test_rend_null_meme_quand_l_annee_anterieure_existe_mais_reste_vide(
    db: _AsyncBridge,
) -> None:
    """L'année 2025-2026 est bien créée, personne n'y a été réinscrit. Une
    année vide ne dit rien de qui était là : c'est exactement la situation où
    conclure « nouveau » facturerait l'entrée à toute l'école."""
    assert AY_PRECEDENTE in {y.id for y in db.session.query(AcademicYear).all()}

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is None


async def test_une_inscription_de_l_annee_courante_ne_fait_pas_un_historique(
    db: _AsyncBridge,
) -> None:
    """Les camarades de classe de cette année ne prouvent rien sur l'an dernier."""
    _inscrire(db, 1, FIDELE, annee=AY_COURANTE)

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is None


# ---------------------------------------------------------------------------
# Une école qui a son passé en base
# ---------------------------------------------------------------------------


async def test_un_eleve_deja_inscrit_l_an_dernier_n_est_pas_nouveau(db: _AsyncBridge) -> None:
    _inscrire(db, 1, FIDELE)

    suggested, reason = await _suggestion(db, FIDELE)

    assert suggested is False
    assert reason


async def test_un_eleve_inconnu_est_nouveau_des_lors_que_l_ecole_a_un_passe(
    db: _AsyncBridge,
) -> None:
    """L'historique existe — d'autres élèves y figurent — et celui-ci n'y est
    pas : la suggestion devient légitime."""
    _inscrire(db, 1, FIDELE)

    suggested, _reason = await _suggestion(db, ARRIVANT)

    assert suggested is True


async def test_un_redoublant_reste_un_ancien(db: _AsyncBridge) -> None:
    """Il refait sa 6ème : le niveau ne change rien à son ancienneté."""
    _inscrire(db, 1, FIDELE, classe=CLASSE_6E_A)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is False


# ---------------------------------------------------------------------------
# Le périmètre des statuts, partagé avec le rapport approfondi
# ---------------------------------------------------------------------------


async def test_une_inscription_rejetee_ne_compte_pas_comme_un_passage(
    db: _AsyncBridge,
) -> None:
    """Un dossier refusé n'a jamais occupé de place : le compter ferait passer
    pour ancien un élève qui n'a jamais mis les pieds dans l'école."""
    _inscrire(db, 1, FIDELE, statut=EnrollmentStatus.REJETE)
    _inscrire(db, 2, ARRIVANT)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is True


async def test_une_inscription_en_validation_compte_comme_un_passage(
    db: _AsyncBridge,
) -> None:
    """C'est le périmètre déjà retenu par les statistiques DREN : on ne le
    change pas d'un usage à l'autre."""
    _inscrire(db, 1, FIDELE, statut=EnrollmentStatus.EN_VALIDATION)

    suggested, _reason = await _suggestion(db, FIDELE)

    assert suggested is False


def test_les_statuts_comptes_sont_ceux_du_rapport_approfondi() -> None:
    """Deux listes de statuts finiraient par diverger, et une seule bougerait
    le jour où quelqu'un ajoute un statut d'inscription."""
    from app.services.deep_report import _context

    assert _context._COUNTED_STATUSES is enrollment_history.COUNTED_STATUSES


# ---------------------------------------------------------------------------
# Le prédicat groupé, celui du rapport approfondi
# ---------------------------------------------------------------------------


async def test_le_rapport_lit_les_couples_eleve_niveau_deja_frequentes(
    db: _AsyncBridge,
) -> None:
    """La requête groupée du rapport et le prédicat unitaire du formulaire
    répondent à la même question sur les mêmes lignes."""
    _inscrire(db, 1, FIDELE, classe=CLASSE_6E_A)

    couples, has_history = await enrollment_history.levels_attended_before(
        db,  # type: ignore[arg-type]
        date(2026, 9, 1),
    )

    assert has_history is True
    assert (FIDELE, LEVEL_6E) in couples


async def test_le_rapport_n_affirme_rien_sans_historique(db: _AsyncBridge) -> None:
    """`has_history` à False laisse la colonne Red / Non Red vide, plutôt que
    d'annoncer « Non Red » pour tout le monde."""
    couples, has_history = await enrollment_history.levels_attended_before(
        db,  # type: ignore[arg-type]
        date(2026, 9, 1),
    )

    assert has_history is False
    assert couples == set()


# ---------------------------------------------------------------------------
# La déduction faite à la création d'une inscription
# ---------------------------------------------------------------------------


async def test_la_deduction_rend_null_sans_historique(db: _AsyncBridge) -> None:
    """Le serveur ne remplit pas la case à la place de l'école."""
    deduit = await enrollment_history.deduce_new_student(
        db,  # type: ignore[arg-type]
        ARRIVANT,
        AY_COURANTE,
    )

    assert deduit is None


async def test_une_annee_inconnue_est_refusee(db: _AsyncBridge) -> None:
    """Mieux vaut un 404 lisible qu'une suggestion calculée sur une date vide."""
    with pytest.raises(NotFoundError):
        await enrollment_history.suggest_new_student(
            db,  # type: ignore[arg-type]
            ARRIVANT,
            9999,
        )
