"""Les compteurs d'inscriptions du bandeau suivent une année, jamais toutes.

Mêlées toutes années, ils annonçaient 771 dossiers quand la liste, filtrée
sur l'année en cours, et les statistiques en montraient d'autres.
"""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student
from app.repositories.admin_repository import get_admin_summary

PASSEE, EN_COURS = 1, 2


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
    with Session(moteur) as s:
        s.add_all(
            [
                AcademicYear(
                    id=PASSEE,
                    name="2024-2025",
                    start_date=date(2024, 9, 9),
                    end_date=date(2025, 6, 30),
                    is_current=False,
                ),
                AcademicYear(
                    id=EN_COURS,
                    name="2025-2026",
                    start_date=date(2025, 9, 8),
                    end_date=date(2026, 6, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=1, name="6eme A", level_id=1),
                *[
                    Student(id=i, last_name=f"ELEVE{i}", first_name="X", enrollment_number=f"M{i}")
                    for i in range(1, 6)
                ],
            ]
        )
        s.flush()
        lignes = [
            (PASSEE, EnrollmentStatus.VALIDE),
            (PASSEE, EnrollmentStatus.VALIDE),
            (PASSEE, EnrollmentStatus.REJETE),
            (EN_COURS, EnrollmentStatus.VALIDE),
            (EN_COURS, EnrollmentStatus.EN_VALIDATION),
        ]
        s.add_all(
            [
                Enrollment(
                    id=10 + n,
                    student_id=n + 1,
                    class_id=1,
                    academic_year_id=annee,
                    status=statut.value,
                )
                for n, (annee, statut) in enumerate(lignes)
            ]
        )
        s.commit()
        yield s


@pytest.mark.asyncio
async def test_counts_only_the_current_year_by_default(db: Session) -> None:
    summary = await get_admin_summary(_Pont(db))

    assert summary["enrollments"] == {"total": 2, "valid": 1, "pending": 1, "closed": 0}


@pytest.mark.asyncio
async def test_counts_the_requested_year(db: Session) -> None:
    summary = await get_admin_summary(_Pont(db), academic_year_id=PASSEE)

    assert summary["enrollments"] == {"total": 3, "valid": 2, "pending": 0, "closed": 1}
