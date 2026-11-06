"""Statistiques DREN : taux de réussite par niveau et sexe non renseigné.

Recette du 2026-11-05 : le graphique « taux de réussite par niveau » répétait
le taux de l'établissement sur chaque barre, et l'effectif (716) dépassait
garçons + filles (357 + 357) sans que le document dise pourquoi.

La requête par niveau tourne ici sur une vraie base SQLite en mémoire ; les
exports sont générés et relus, pas inspectés dans leur code.
"""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
import pytest_asyncio
from openpyxl import load_workbook
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.academic import AcademicYear, Class, Level
from app.models.grade import Bulletin
from app.repositories import dren_stats_repository as repo
from app.schemas.dren_stats import ClassStats, DrenStatsResponse, LevelStats
from app.services.exports.dren_stats_xlsx import generate_dren_stats_xlsx

AY = 1
SIXIEME, TROISIEME = 1, 2
TABLES = ("academic_years", "levels", "classes", "bulletins")


def _miroir() -> MetaData:
    miroir = MetaData()
    for nom in TABLES:
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
                    id=AY,
                    name="2025-2026",
                    start_date=date(2025, 9, 1),
                    end_date=date(2026, 7, 31),
                    is_current=True,
                ),
                Level(id=SIXIEME, name="6ème", order=1),
                Level(id=TROISIEME, name="3ème", order=4),
                Class(id=10, name="6ème A", level_id=SIXIEME, max_students=40),
                Class(id=20, name="3ème A", level_id=TROISIEME, max_students=40),
            ]
        )
        await session.flush()
        yield session
    await moteur.dispose()


def _bulletin(student: int, class_id: int, trimester: int, average: str) -> Bulletin:
    return Bulletin(
        student_id=student,
        class_id=class_id,
        academic_year_id=AY,
        trimester=trimester,
        average=Decimal(average),
        is_published=True,
    )


@pytest.mark.asyncio
async def test_each_level_gets_its_own_success_rate(db: AsyncSession) -> None:
    # 6ème : 3 réussites sur 4 ; 3ème : 1 sur 4. Le taux global est 50 %.
    db.add_all(
        [_bulletin(i, 10, 1, a) for i, a in enumerate(["12", "10.00", "15", "9.99"], 1)]
        + [_bulletin(i, 20, 1, a) for i, a in enumerate(["8", "11", "7", "9"], 11)]
    )
    await db.flush()

    rates = await repo.get_success_rate_by_level(db, AY)
    global_rate, *_ = await repo.get_bulletin_rates(db, AY)

    assert rates == {SIXIEME: 75.0, TROISIEME: 25.0}
    assert global_rate == 50.0


@pytest.mark.asyncio
async def test_level_rates_use_the_same_trimester_as_the_global_rate(db: AsyncSession) -> None:
    # Le trimestre 1 est entièrement réussi en 6ème, le trimestre 2 entièrement
    # raté : seul le plus récent compte, comme pour le taux de l'établissement.
    db.add_all(
        [_bulletin(1, 10, 1, "16"), _bulletin(2, 10, 1, "14")]
        + [_bulletin(1, 10, 2, "6"), _bulletin(2, 10, 2, "7")]
    )
    await db.flush()

    assert await repo.get_success_rate_by_level(db, AY) == {SIXIEME: 0.0}


@pytest.mark.asyncio
async def test_a_level_without_bulletins_has_no_rate_rather_than_zero(db: AsyncSession) -> None:
    db.add(_bulletin(1, 10, 1, "12"))
    await db.flush()

    rates = await repo.get_success_rate_by_level(db, AY)

    assert TROISIEME not in rates


@pytest.mark.asyncio
async def test_no_bulletin_at_all_gives_no_rate(db: AsyncSession) -> None:
    assert await repo.get_success_rate_by_level(db, AY) == {}


def _stats(total: int, male: int, female: int) -> DrenStatsResponse:
    classe = ClassStats(
        class_id=10, class_name="6ème A", total_students=total, male_count=male, female_count=female
    )
    niveau = LevelStats(
        level_id=SIXIEME,
        level_name="6ème",
        total_students=total,
        male_count=male,
        female_count=female,
        success_rate=75.0,
        classes=[classe],
    )
    return DrenStatsResponse(
        academic_year_id=AY,
        academic_year_name="2025-2026",
        total_students=total,
        male_count=male,
        female_count=female,
        levels=[niveau],
        subjects=[],
    )


def test_unspecified_count_closes_the_gap_between_total_and_genders() -> None:
    stats = _stats(716, 357, 357)

    assert stats.unspecified_count == 2
    assert stats.levels[0].unspecified_count == 2
    assert stats.levels[0].classes[0].unspecified_count == 2
    assert stats.model_dump()["unspecified_count"] == 2


def test_xlsx_shows_students_without_a_recorded_sex() -> None:
    classeur = load_workbook(BytesIO(generate_dren_stats_xlsx(_stats(41, 19, 21))))

    synthese = {row[0]: row[1] for row in classeur["Synthèse"].iter_rows(values_only=True)}
    assert synthese["Sexe non renseigné"] == 1

    niveaux = list(classeur["Niveaux & classes"].iter_rows(values_only=True))
    entete, ligne_classe, total = niveaux[0], niveaux[1], niveaux[-1]
    colonne = entete.index("Non renseigné")
    assert ligne_classe[colonne] == 1
    assert total[colonne] == 1
    assert ligne_classe[2] == ligne_classe[3] + ligne_classe[4] + ligne_classe[colonne]
