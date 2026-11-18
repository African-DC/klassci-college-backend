"""Les pastilles « Affectation » comptent et filtrent tous les résultats.

La liste se charge par pages. Compter ou filtrer côté navigateur ne voyait
que les lignes déjà chargées : une pastille annonçait 6 affectés sur une
classe qui en comptait 40.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import AssignmentStatus, Enrollment, EnrollmentStatus
from app.models.user import Student
from app.repositories import enrollment_repository as repo

ANNEE, AUTRE = 1, 2


class _Pont:
    """Allure d'une `AsyncSession` pour une session synchrone : seul `execute` sert."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


@pytest.fixture()
def db() -> Iterator[Session]:
    moteur = create_engine("sqlite://")

    @compiles(BigInteger, "sqlite")
    def _bigint(type_, compiler, **kw):  # noqa: ARG001
        return "INTEGER"

    Base.metadata.create_all(moteur)
    affectations = [
        (ANNEE, AssignmentStatus.AFFECTE.value),
        (ANNEE, AssignmentStatus.REAFFECTE.value),
        (ANNEE, AssignmentStatus.NON_AFFECTE.value),
        (ANNEE, None),
        (ANNEE, None),
        (AUTRE, AssignmentStatus.AFFECTE.value),
    ]
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=True,
                ),
                AcademicYear(
                    id=AUTRE,
                    name="2026-2027",
                    start_date=date(2026, 9, 7),
                    end_date=date(2027, 6, 30),
                    is_current=False,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                *[
                    Student(id=i, last_name=f"ELEVE{i}", first_name="X", enrollment_number=f"M{i}")
                    for i in range(1, len(affectations) + 1)
                ],
            ]
        )
        s.flush()
        s.add_all(
            [
                Enrollment(
                    id=10 + n,
                    student_id=n + 1,
                    class_id=1,
                    academic_year_id=annee,
                    status=EnrollmentStatus.VALIDE.value,
                    assignment_status=affectation,
                )
                for n, (annee, affectation) in enumerate(affectations)
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_counts_cover_every_filtered_enrollment(db: Session) -> None:
    counts = await repo.assignment_counts(_Pont(db), academic_year_id=ANNEE)

    # Réaffecté compte avec affecté ; l'autre année n'entre pas.
    assert counts == {"tous": 5, "affectes": 2, "non_affectes": 1, "non_renseigne": 2}


@pytest.mark.asyncio
async def test_list_filters_on_assignment_server_side(db: Session) -> None:
    rows, total = await repo.list_enrollments(
        _Pont(db), academic_year_id=ANNEE, assignment="affectes", size=1
    )

    # Le total compte toutes les lignes, pas la seule page renvoyée.
    assert total == 2
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_unfilled_assignment_is_its_own_pill(db: Session) -> None:
    _, total = await repo.list_enrollments(
        _Pont(db), academic_year_id=ANNEE, assignment="non_renseigne"
    )

    assert total == 2


def test_counts_route_is_not_read_as_an_enrollment_id() -> None:
    from starlette.routing import Match

    from app.routers.enrollments import router

    scope = {"type": "http", "path": f"{router.prefix}/assignment-counts", "method": "GET"}
    first = next(r for r in router.routes if r.matches(scope)[0] is Match.FULL)

    assert first.name == "enrollment_assignment_counts"
