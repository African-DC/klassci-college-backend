"""Service DREN stats — agrégation des statistiques pour les rapports DREN."""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.repositories import dren_stats_repository as repo
from app.schemas.dren_stats import (
    ClassStats,
    DrenExportResponse,
    DrenStatsResponse,
    LevelStats,
    SubjectStats,
)

logger = logging.getLogger(__name__)


async def get_dren_stats(db: AsyncSession, academic_year_id: int) -> DrenStatsResponse:
    """Calcule les statistiques DREN complètes pour une année scolaire."""
    # 1. Verify academic year exists
    academic_year = await repo.get_academic_year(db, academic_year_id)
    if not academic_year:
        raise NotFoundError("AcademicYear", academic_year_id)

    # 2. Enrollment counts by level
    level_rows = await repo.get_enrollment_counts_by_level(db, academic_year_id)

    # 3. Enrollment counts by class (with averages)
    class_rows = await repo.get_enrollment_counts_by_class(db, academic_year_id)

    # Build class stats grouped by level_id
    classes_by_level: dict[int, list[ClassStats]] = {}
    for row in class_rows:
        class_stat = ClassStats(
            class_id=row[0],
            class_name=row[1],
            total_students=row[3],
            male_count=row[4],
            female_count=row[5],
            average=_round_decimal(row[6]),
        )
        classes_by_level.setdefault(row[2], []).append(class_stat)

    # Build level stats
    levels: list[LevelStats] = []
    total_students = 0
    total_male = 0
    total_female = 0
    for row in level_rows:
        level_id = row[0]
        level_stat = LevelStats(
            level_id=level_id,
            level_name=row[1],
            total_students=row[3],
            male_count=row[4],
            female_count=row[5],
            classes=classes_by_level.get(level_id, []),
        )
        levels.append(level_stat)
        total_students += row[3]
        total_male += row[4]
        total_female += row[5]

    # 4. Success/failure/redoublement/exclusion rates
    success_rate, failure_rate, redoublement_rate, exclusion_rate = (
        await repo.get_bulletin_rates(db, academic_year_id)
    )

    # 5. Subject averages
    subject_avg_rows = await repo.get_subject_averages(db, academic_year_id)

    # 6. Teacher counts per subject
    teacher_count_rows = await repo.get_teacher_counts_by_subject(db, academic_year_id)
    teacher_map: dict[int, int] = {row[0]: row[1] for row in teacher_count_rows}

    # Build subject stats
    subjects: list[SubjectStats] = []
    for row in subject_avg_rows:
        subject_id = row[0]
        subjects.append(
            SubjectStats(
                subject_id=subject_id,
                subject_name=row[1],
                overall_average=_round_decimal(row[2]),
                teacher_count=teacher_map.get(subject_id, 0),
            )
        )

    # Add subjects that have teachers but no grades yet
    subjects_with_grades = {s.subject_id for s in subjects}
    for subject_id, count in teacher_map.items():
        if subject_id not in subjects_with_grades:
            # We don't have the subject name here — skip these
            # They will appear once grades are entered
            pass

    return DrenStatsResponse(
        academic_year_id=academic_year_id,
        academic_year_name=academic_year.name,
        total_students=total_students,
        male_count=total_male,
        female_count=total_female,
        success_rate=success_rate,
        failure_rate=failure_rate,
        redoublement_rate=redoublement_rate,
        exclusion_rate=exclusion_rate,
        levels=levels,
        subjects=subjects,
    )


async def export_dren_stats(db: AsyncSession, academic_year_id: int) -> DrenExportResponse:
    """Export des statistiques DREN (placeholder — retourne les données JSON)."""
    data = await get_dren_stats(db, academic_year_id)
    return DrenExportResponse(
        export_url=None,
        data=data,
    )


def _round_decimal(value: Decimal | None) -> Decimal | None:
    """Arrondit un Decimal à 2 décimales, retourne None si None."""
    if value is None:
        return None
    return Decimal(str(round(value, 2)))
