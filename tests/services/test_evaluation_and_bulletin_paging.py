"""Deux listes ne doivent plus rapatrier toute l'école pour en montrer vingt.

`/evaluations` et `/reports/bulletins` ignoraient le `size` demandé et
renvoyaient l'intégralité de la base : 772 évaluations accompagnées de leurs
30 340 notes, 2 148 bulletins accompagnés de toutes leurs moyennes par
matière. Le tout pour afficher une page de vingt lignes et deux compteurs.

Les tests montent le vrai schéma sur SQLite et appellent les vraies
fonctions, comme `test_money_single_truth` : ils exécutent le SQL.
"""

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import NotFoundError
from app.models.academic import Class, Subject
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import (
    Bulletin,
    Evaluation,
    EvaluationType,
    Grade,
    GradeStatus,
    SubjectAverage,
)
from app.models.user import Student, TeacherProfile
from app.services import grades_service, reports_service

AY = 2026
CLASSE, MATIERE, PROF = 10, 20, 30

_TABLES = (
    "evaluations",
    "grades",
    "subjects",
    "classes",
    "teacher_profiles",
    "bulletins",
    "subject_averages",
    "students",
    "enrollments",
)


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.flush()


def _sqlite_schema() -> list[Table]:
    """Le schéma transposé pour SQLite, sur une copie jamais partagée."""
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    tables = []
    for nom in _TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


def _session() -> Session:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)
    return Session(engine)


def _referentiel(session: Session) -> None:
    session.add_all(
        [
            Class(id=CLASSE, name="6eme A", level_id=1, max_students=40),
            Subject(id=MATIERE, name="Mathematiques", coefficient=4),
            TeacherProfile(id=PROF, user_id=1, first_name="Aissatou", last_name="Diallo"),
        ]
    )
    session.flush()


def _evaluation(numero: int) -> Evaluation:
    return Evaluation(
        id=numero,
        title=f"Devoir {numero}",
        type=EvaluationType.DEVOIR,
        date=date(2026, 1, 1 + (numero % 28)),
        coefficient=1,
        subject_id=MATIERE,
        class_id=CLASSE,
        teacher_id=PROF,
        academic_year_id=AY,
        trimester=1,
    )


# ---------------------------------------------------------------------------
# Évaluations
# ---------------------------------------------------------------------------


@pytest.fixture
def ecole_avec_25_evaluations() -> Iterator[_AsyncBridge]:
    """Vingt-cinq évaluations dans la même classe, aucune note saisie."""
    session = _session()
    _referentiel(session)
    session.add_all([_evaluation(numero) for numero in range(1, 26)])
    session.flush()
    yield _AsyncBridge(session)
    session.close()


@pytest.mark.asyncio
async def test_une_page_rend_le_nombre_d_elements_demande(
    ecole_avec_25_evaluations: _AsyncBridge,
) -> None:
    """`size=10` rend dix évaluations, pas les vingt-cinq de l'école."""
    page = await grades_service.list_evaluations(
        ecole_avec_25_evaluations,  # type: ignore[arg-type]
        page=1,
        size=10,
    )

    assert len(page["items"]) == 10
    assert page["page"] == 1
    assert page["size"] == 10


@pytest.mark.asyncio
async def test_le_total_est_celui_de_l_ecole_pas_celui_de_la_page(
    ecole_avec_25_evaluations: _AsyncBridge,
) -> None:
    """Un écran qui affiche « 25 évaluations » lit l'enveloppe, pas `items`."""
    page = await grades_service.list_evaluations(
        ecole_avec_25_evaluations,  # type: ignore[arg-type]
        page=1,
        size=10,
    )

    assert page["total"] == 25
    assert page["total"] != len(page["items"])


@pytest.mark.asyncio
async def test_deux_pages_successives_ne_repetent_aucune_evaluation(
    ecole_avec_25_evaluations: _AsyncBridge,
) -> None:
    """Le tri départage les évaluations de même date, sinon une ligne se répète."""
    premiere = await grades_service.list_evaluations(
        ecole_avec_25_evaluations,  # type: ignore[arg-type]
        page=1,
        size=10,
    )
    seconde = await grades_service.list_evaluations(
        ecole_avec_25_evaluations,  # type: ignore[arg-type]
        page=2,
        size=10,
    )

    identifiants = [item["id"] for item in premiere["items"] + seconde["items"]]
    assert len(identifiants) == len(set(identifiants)) == 20


@pytest.fixture
def evaluation_partiellement_notee() -> Iterator[_AsyncBridge]:
    """Cinq élèves : trois notes saisies, un zéro d'office, une case vide."""
    session = _session()
    _referentiel(session)
    session.add(_evaluation(1))
    session.flush()
    statuts = [
        (GradeStatus.ENTERED, Decimal("14.00")),
        (GradeStatus.ENTERED, Decimal("11.50")),
        (GradeStatus.ENTERED, Decimal("8.00")),
        (GradeStatus.ABSENT, Decimal("0.00")),
        (GradeStatus.PENDING, None),
    ]
    for rang, (statut, valeur) in enumerate(statuts, start=1):
        session.add(Grade(id=rang, evaluation_id=1, student_id=rang, status=statut, value=valeur))
    session.flush()
    yield _AsyncBridge(session)
    session.close()


@pytest.mark.asyncio
async def test_les_compteurs_restent_exacts_apres_l_agregat(
    evaluation_partiellement_notee: _AsyncBridge,
) -> None:
    """Cinq élèves, trois notes saisies — comptés en SQL, pas en mémoire.

    L'absent porte un zéro d'office : il compte parmi les élèves de
    l'évaluation, pas parmi les notes saisies.
    """
    page = await grades_service.list_evaluations(
        evaluation_partiellement_notee,  # type: ignore[arg-type]
        page=1,
        size=20,
    )

    (evaluation,) = page["items"]
    assert evaluation["total_students"] == 5
    assert evaluation["graded_students"] == 3


@pytest.fixture
def evaluation_sans_aucune_note() -> Iterator[_AsyncBridge]:
    """Une évaluation créée puis jamais rattachée à un élève."""
    session = _session()
    _referentiel(session)
    session.add(_evaluation(1))
    session.flush()
    yield _AsyncBridge(session)
    session.close()


@pytest.mark.asyncio
async def test_une_evaluation_sans_note_rend_zero_et_zero(
    evaluation_sans_aucune_note: _AsyncBridge,
) -> None:
    """Absente de l'agrégat, elle vaut zéro sur zéro, et surtout pas une erreur."""
    page = await grades_service.list_evaluations(
        evaluation_sans_aucune_note,  # type: ignore[arg-type]
        page=1,
        size=20,
    )

    (evaluation,) = page["items"]
    assert evaluation["total_students"] == 0
    assert evaluation["graded_students"] == 0


@pytest.mark.asyncio
async def test_la_fiche_d_une_evaluation_porte_les_memes_compteurs(
    evaluation_partiellement_notee: _AsyncBridge,
) -> None:
    """L'écran de saisie lit une évaluation seule et retrouve les mêmes nombres."""
    evaluation = await grades_service.get_evaluation(
        evaluation_partiellement_notee,  # type: ignore[arg-type]
        eval_id=1,
    )

    assert evaluation["total_students"] == 5
    assert evaluation["graded_students"] == 3


@pytest.mark.asyncio
async def test_une_evaluation_inconnue_leve_un_introuvable(
    evaluation_partiellement_notee: _AsyncBridge,
) -> None:
    """Un identifiant qui n'existe pas donne un 404, pas une page vide."""
    with pytest.raises(NotFoundError):
        await grades_service.get_evaluation(
            evaluation_partiellement_notee,  # type: ignore[arg-type]
            eval_id=999,
        )


# ---------------------------------------------------------------------------
# Bulletins
# ---------------------------------------------------------------------------


@pytest.fixture
def ecole_avec_25_bulletins() -> Iterator[_AsyncBridge]:
    """Vingt-cinq élèves inscrits, leur bulletin et une moyenne par matière."""
    session = _session()
    _referentiel(session)
    for numero in range(1, 26):
        session.add(Student(id=numero, first_name=f"Eleve{numero}", last_name="Traore"))
        session.add(
            Enrollment(
                id=numero,
                student_id=numero,
                class_id=CLASSE,
                academic_year_id=AY,
                status=EnrollmentStatus.VALIDE,
            )
        )
        session.add(
            Bulletin(
                id=numero,
                student_id=numero,
                class_id=CLASSE,
                academic_year_id=AY,
                trimester=1,
                average=Decimal("12.00"),
                rank=numero,
                is_published=True,
            )
        )
    session.flush()
    for numero in range(1, 26):
        session.add(
            SubjectAverage(
                id=numero,
                bulletin_id=numero,
                subject_id=MATIERE,
                student_id=numero,
                trimester=1,
                average=Decimal("12.00"),
                coefficient=4,
            )
        )
    session.flush()
    yield _AsyncBridge(session)
    session.close()


@pytest.mark.asyncio
async def test_une_page_de_bulletins_rend_le_nombre_demande(
    ecole_avec_25_bulletins: _AsyncBridge,
) -> None:
    """`size=10` rend dix bulletins et annonce les vingt-cinq de l'école."""
    reponse = await reports_service.list_bulletins(
        ecole_avec_25_bulletins,  # type: ignore[arg-type]
        page=1,
        size=10,
    )

    assert len(reponse.items) == 10
    assert reponse.total == 25
    assert reponse.page == 1
    assert reponse.size == 10


@pytest.mark.asyncio
async def test_l_effectif_de_la_classe_reste_celui_de_l_ecole(
    ecole_avec_25_bulletins: _AsyncBridge,
) -> None:
    """« 7e sur 25 » : le dénominateur est l'effectif inscrit, pas la page.

    C'est le piège du compteur calculé sur les éléments reçus : paginé, il
    aurait annoncé « 7e sur 10 ».
    """
    reponse = await reports_service.list_bulletins(
        ecole_avec_25_bulletins,  # type: ignore[arg-type]
        page=1,
        size=10,
    )

    assert {bulletin.total_students for bulletin in reponse.items} == {25}
    assert reponse.items[0].subject_averages[0].subject_name == "Mathematiques"


@pytest.mark.asyncio
async def test_la_derniere_page_de_bulletins_est_partielle(
    ecole_avec_25_bulletins: _AsyncBridge,
) -> None:
    """Vingt-cinq bulletins par dix : la troisième page en contient cinq."""
    reponse = await reports_service.list_bulletins(
        ecole_avec_25_bulletins,  # type: ignore[arg-type]
        page=3,
        size=10,
    )

    assert len(reponse.items) == 5
    assert reponse.total == 25
