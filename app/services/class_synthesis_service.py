"""Service : composition + génération du rapport de synthèse de classe (PDF).

Réutilise les bulletins de la classe (un trimestre) et le module pur
`reports_subject_stats` pour produire le palmarès et les statistiques par
matière. Document interne au conseil de classe.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.repositories import reports_repository as repo
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.pdf import generate_class_synthesis_pdf
from app.services.reports_subject_stats import compute_general_stats, compute_subject_stats

_PASS_THRESHOLD = Decimal("10")


def _student_name(student: object) -> str:
    last = getattr(student, "last_name", "") or ""
    first = getattr(student, "first_name", "") or ""
    return f"{last} {first}".strip()


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    stmt = select(Class).where(Class.id == class_id).options(selectinload(Class.level))
    klass = (await db.execute(stmt)).scalar_one_or_none()
    if klass is None:
        raise NotFoundError("Class", class_id)
    return klass


def _subject_directory(class_bulletins: list) -> dict[int, dict[str, str | None]]:
    """subject_id -> {name, teacher_name} depuis les bulletins de la classe."""
    directory: dict[int, dict[str, str | None]] = {}
    for bulletin in class_bulletins:
        for sa in bulletin.subject_averages or []:
            if sa.subject_id in directory or sa.subject is None:
                continue
            teacher = getattr(sa.subject, "teacher", None)
            directory[sa.subject_id] = {
                "name": sa.subject.name,
                "teacher_name": (
                    f"{teacher.first_name} {teacher.last_name}".strip() if teacher else None
                ),
            }
    return directory


async def get_class_synthesis_pdf(
    db: AsyncSession, class_id: int, *, trimester: int, academic_year_id: int
) -> bytes:
    """Génère le rapport de synthèse PDF d'une classe pour un trimestre."""
    klass = await _load_class(db, class_id)
    ay = await db.get(AcademicYear, academic_year_id)
    class_bulletins = await repo.list_bulletins(
        db, class_id=class_id, trimester=trimester, academic_year_id=academic_year_id
    )

    subject_stats = compute_subject_stats(class_bulletins)
    general = compute_general_stats(class_bulletins)
    directory = _subject_directory(class_bulletins)

    palmares = sorted(
        (
            {
                "rank": b.rank,
                "student_name": _student_name(b.student) if b.student else "",
                "average": b.average,
                "mention": b.mention,
            }
            for b in class_bulletins
        ),
        key=lambda e: (e["rank"] is None, e["rank"] or 0),
    )

    subjects = [
        {
            "subject_name": directory.get(sid, {}).get("name", ""),
            "teacher_name": directory.get(sid, {}).get("teacher_name"),
            "class_avg": st["avg"],
            "min": st["min"],
            "max": st["max"],
        }
        for sid, st in subject_stats.items()
    ]
    subjects.sort(key=lambda s: s["subject_name"])

    total = len(class_bulletins)
    passed = sum(
        1 for b in class_bulletins if b.average is not None and b.average >= _PASS_THRESHOLD
    )

    data = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
        "trimester": trimester,
        "academic_year_name": ay.name if ay else "",
        "counts": {"total": total, "passed": passed, "failed": total - passed},
        "class_stats": general,
        "palmares": palmares,
        "subjects": subjects,
        "issued_at": datetime.utcnow(),
    }
    school = await load_school_settings_for_pdf(db)
    return generate_class_synthesis_pdf(data, school)
