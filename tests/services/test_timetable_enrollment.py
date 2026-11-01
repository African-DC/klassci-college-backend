"""Le planning d'une famille suit l'année en cours, pas la réinscription à venir.

Sur la démo, 42 élèves ont une inscription validée cette année et une
réinscription pour l'an prochain. Le portail retenait la plus récente : l'élève
voyait la classe de l'an prochain, sans aucun cours.
"""

from collections.abc import AsyncIterator
from datetime import date

import pytest
from sqlalchemy import Integer, MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear, Class
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.repositories.timetable_repository import get_enrollment_for_student_timetable

THIS_YEAR = 1
NEXT_YEAR = 5
SIXIEME = 10
CINQUIEME = 11
STUDENT = 2


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    mirror = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(mirror)
    tables = [mirror.tables[name] for name in ("academic_years", "classes", "enrollments")]
    for table in tables:
        table.c.id.type = Integer()
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: mirror.create_all(sync, tables=tables))

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add_all(
            [
                AcademicYear(
                    id=THIS_YEAR,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 1),
                    is_current=True,
                ),
                AcademicYear(
                    id=NEXT_YEAR,
                    name="2026-2027",
                    start_date=date(2026, 9, 1),
                    end_date=date(2027, 7, 1),
                    is_current=False,
                ),
                Class(id=SIXIEME, name="6eme A", level_id=1, series_id=None),
                Class(id=CINQUIEME, name="5eme A", level_id=2, series_id=None),
            ]
        )
        await session.commit()
        yield session
    await engine.dispose()


def _enrollment(id_: int, class_id: int, year: int, status: EnrollmentStatus) -> Enrollment:
    return Enrollment(
        id=id_, student_id=STUDENT, class_id=class_id, academic_year_id=year, status=status
    )


@pytest.mark.asyncio
async def test_a_reenrollment_for_next_year_does_not_replace_the_current_class(
    db: AsyncSession,
) -> None:
    db.add_all(
        [
            _enrollment(1, SIXIEME, THIS_YEAR, EnrollmentStatus.VALIDE),
            _enrollment(777, CINQUIEME, NEXT_YEAR, EnrollmentStatus.PROSPECT),
        ]
    )
    await db.commit()

    enrollment = await get_enrollment_for_student_timetable(db, STUDENT)

    assert enrollment is not None
    assert enrollment.class_id == SIXIEME
    assert enrollment.class_.name == "6eme A"


@pytest.mark.asyncio
async def test_a_student_only_enrolled_for_next_year_still_has_a_class(db: AsyncSession) -> None:
    db.add(_enrollment(777, CINQUIEME, NEXT_YEAR, EnrollmentStatus.PROSPECT))
    await db.commit()

    enrollment = await get_enrollment_for_student_timetable(db, STUDENT)

    assert enrollment is not None
    assert enrollment.class_id == CINQUIEME


@pytest.mark.asyncio
async def test_a_cancelled_current_enrollment_is_ignored(db: AsyncSession) -> None:
    db.add_all(
        [
            _enrollment(1, SIXIEME, THIS_YEAR, EnrollmentStatus.ANNULE),
            _enrollment(777, CINQUIEME, NEXT_YEAR, EnrollmentStatus.PROSPECT),
        ]
    )
    await db.commit()

    enrollment = await get_enrollment_for_student_timetable(db, STUDENT)

    assert enrollment is not None
    assert enrollment.class_id == CINQUIEME
