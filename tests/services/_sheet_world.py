"""Une petite école sur SQLite, pour les tests de la fiche de renseignements.

Trois années (2024-2025 et 2025-2026 révolues, 2026-2027 courante), cinq niveaux nommés
comme les écoles les nomment, une classe par niveau. Les services tournent
dessus avec leur vrai SQL, via une façade d'`AsyncSession` posée sur une
session synchrone.
"""

from collections.abc import Iterator
from datetime import date
from typing import Any

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (enregistre toutes les tables dans les métadonnées)
from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level, SchoolSettings, Series
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.user import Student, User

ACTEUR = 1
AN_PASSE = 1
AN_COURANT = 2
AN_AVANT_DERNIER = 3

CLASSE_6E = 10
CLASSE_5E = 11
CLASSE_4E = 12
CLASSE_3E = 13
CLASSE_TLE_D = 14


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_: Any, compiler: Any, **kw: Any) -> str:  # noqa: ARG001
    return "INTEGER"


class AsyncBridge:
    """Une `AsyncSession` de façade posée sur une session synchrone réelle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def execute(self, statement: object, *args: object) -> object:
        return self.session.execute(statement, *args)  # type: ignore[call-overload]

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def delete(self, instance: object) -> None:
        self.session.delete(instance)

    async def refresh(self, instance: object, *a: object, **k: object) -> None:
        self.session.refresh(instance)

    def begin_nested(self) -> "_Nested":
        return _Nested(self.session)


class _Nested:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._tx: Any = None

    async def __aenter__(self) -> Any:
        self._tx = self._session.begin_nested()
        return self._tx

    async def __aexit__(self, exc_type: object, *_: object) -> bool:
        if exc_type is not None:
            self._tx.rollback()
            return False
        self._tx.commit()
        return False


def build_school(*, history_reliable: bool = False) -> Iterator[Session]:
    """Base neuve : années, niveaux, classes, un utilisateur, des réglages."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                User(id=ACTEUR, email="compta@ecole.ci", hashed_password="x", role="staff"),
                SchoolSettings(
                    school_name="Collège Test", enrollment_history_is_reliable=history_reliable
                ),
                AcademicYear(
                    id=AN_PASSE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=False,
                ),
                AcademicYear(
                    id=AN_AVANT_DERNIER,
                    name="2024-2025",
                    start_date=date(2024, 9, 1),
                    end_date=date(2025, 7, 31),
                    is_current=False,
                ),
                AcademicYear(
                    id=AN_COURANT,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 31),
                    is_current=True,
                ),
                Level(id=1, name="6ème", order=1),
                Level(id=2, name="Cinquième", order=2),
                Level(id=3, name="4eme", order=3),
                Level(id=4, name="3ème", order=4),
                Level(id=7, name="Terminale", order=7),
                Series(id=1, level_id=7, name="D"),
                Class(id=CLASSE_6E, name="6ème 1", level_id=1),
                Class(id=CLASSE_5E, name="5ème 1", level_id=2),
                Class(id=CLASSE_4E, name="4ème 1", level_id=3),
                Class(id=CLASSE_3E, name="3ème 1", level_id=4),
                Class(id=CLASSE_TLE_D, name="Tle D", level_id=7, series_id=1),
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def add_student(session: Session, student_id: int, last: str, first: str, **kw: Any) -> Student:
    student = Student(id=student_id, last_name=last, first_name=first, **kw)
    session.add(student)
    session.flush()
    return student


def add_enrollment(
    session: Session,
    enrollment_id: int,
    student_id: int,
    class_id: int,
    year_id: int,
    status: EnrollmentStatus = EnrollmentStatus.VALIDE,
    **kw: Any,
) -> Enrollment:
    enrollment = Enrollment(
        id=enrollment_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=year_id,
        status=status,
        **kw,
    )
    session.add(enrollment)
    session.flush()
    return enrollment
