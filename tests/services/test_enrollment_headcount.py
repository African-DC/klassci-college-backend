"""« Élèves inscrits » : un seul effectif, quel que soit l'écran.

Recette du 2026-11-05 : 817 sur le tableau de bord, 716 dans les statistiques
DREN, pour la même école le même jour. Ce test compte sur une vraie base
SQLite ce que le prédicat partagé retient et ce qu'il écarte.
"""

from collections.abc import AsyncIterator
from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, MetaData, Table, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.repositories.enrollment_headcount import counted_in_headcount, current_year_enrollment

COURANTE, PASSEE = 1, 2


def _miroir() -> MetaData:
    miroir = MetaData()
    for nom in ("academic_years", "enrollments"):
        Base.metadata.tables[nom].to_metadata(miroir)
    for table in list(miroir.tables.values()):
        for fk in table.foreign_keys:
            cible = fk.target_fullname.split(".")[0]
            if cible not in miroir.tables:
                Table(cible, miroir, Column("id", Integer, primary_key=True))
        if "id" in table.c:
            table.c.id.type = Integer()
    return miroir


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    moteur = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with moteur.begin() as conn:
        await conn.run_sync(lambda c: _miroir().create_all(c))
    async with AsyncSession(moteur, expire_on_commit=False) as session:
        session.add_all(
            [
                AcademicYear(
                    id=COURANTE,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=True,
                ),
                AcademicYear(
                    id=PASSEE,
                    name="2024-2025",
                    start_date=date(2024, 9, 1),
                    end_date=date(2025, 7, 31),
                    is_current=False,
                ),
            ]
        )
        await session.flush()
        yield session
    await moteur.dispose()


def _inscription(
    eleve: int, annee: int, statut: EnrollmentStatus, *, archivee: bool = False
) -> Enrollment:
    return Enrollment(
        student_id=eleve,
        class_id=1,
        academic_year_id=annee,
        status=statut,
        archived_at=datetime(2026, 1, 10) if archivee else None,
    )


async def _compte(db: AsyncSession, predicat: object) -> int:
    return int((await db.execute(select(func.count(Enrollment.id)).where(predicat))).scalar() or 0)


@pytest.mark.asyncio
async def test_headcount_keeps_only_validated_current_year_enrollments(db: AsyncSession) -> None:
    db.add_all(
        [
            _inscription(1, COURANTE, EnrollmentStatus.VALIDE),
            _inscription(2, COURANTE, EnrollmentStatus.VALIDE),
            _inscription(3, COURANTE, EnrollmentStatus.EN_VALIDATION),
            _inscription(4, COURANTE, EnrollmentStatus.PROSPECT),
            _inscription(5, COURANTE, EnrollmentStatus.VALIDE, archivee=True),
            _inscription(1, PASSEE, EnrollmentStatus.VALIDE),
        ]
    )
    await db.flush()

    assert await _compte(db, counted_in_headcount()) == 2


@pytest.mark.asyncio
async def test_pending_files_are_counted_apart_and_only_for_this_year(db: AsyncSession) -> None:
    db.add_all(
        [
            _inscription(3, COURANTE, EnrollmentStatus.EN_VALIDATION),
            _inscription(6, PASSEE, EnrollmentStatus.EN_VALIDATION),
            _inscription(7, COURANTE, EnrollmentStatus.EN_VALIDATION, archivee=True),
        ]
    )
    await db.flush()

    assert await _compte(db, current_year_enrollment(EnrollmentStatus.EN_VALIDATION)) == 1
