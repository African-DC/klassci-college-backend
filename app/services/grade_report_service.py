"""Service : composition + génération du relevé de notes de classe (PDF).

Charge les évaluations saisies pour une (classe, matière, trimestre, année),
calcule pour chaque élève sa moyenne pondérée par les coefficients
d'évaluation et son rang (classement compétition), puis les statistiques de
classe (moyenne, min, max, taux de saisie). Document de travail interne.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class, Subject
from app.models.grade import Evaluation
from app.repositories import grades_repository, reports_repository
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.pdf import generate_grade_report_pdf


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    stmt = select(Class).where(Class.id == class_id).options(selectinload(Class.level))
    klass = (await db.execute(stmt)).scalar_one_or_none()
    if klass is None:
        raise NotFoundError("Class", class_id)
    return klass


def _weighted_average(pairs: list[tuple[Decimal, int]]) -> Decimal | None:
    """Moyenne pondérée = Σ(note × coef) / Σ(coef), arrondie à 2 décimales."""
    total_coeff = sum(c for _, c in pairs)
    if total_coeff == 0:
        return None
    total_val = sum(v * c for v, c in pairs)
    raw = Decimal(str(total_val)) / Decimal(str(total_coeff))
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _assign_ranks(rows: list[dict[str, Any]]) -> None:
    """Classement compétition décroissant sur la moyenne (ex-aequo partagés)."""
    ranked = sorted(
        (r for r in rows if r["average"] is not None),
        key=lambda r: r["average"],
        reverse=True,
    )
    rank = 1
    for i, row in enumerate(ranked):
        if i > 0 and row["average"] == ranked[i - 1]["average"]:
            row["rank"] = ranked[i - 1]["rank"]
        else:
            row["rank"] = rank
        rank = i + 2
    for row in rows:
        row.setdefault("rank", None)


def _build_student_rows(
    students: list[Any], evaluations: list[Evaluation]
) -> tuple[list[dict[str, Any]], int]:
    """Construit les lignes élèves + retourne le nombre de cellules notées."""
    grades_by_eval: dict[int, dict[int, Decimal | None]] = {
        ev.id: {g.student_id: g.value for g in (ev.grades or [])} for ev in evaluations
    }
    filled_cells = 0
    rows: list[dict[str, Any]] = []
    for s in students:
        values: list[Decimal | None] = []
        pairs: list[tuple[Decimal, int]] = []
        for ev in evaluations:
            value = grades_by_eval.get(ev.id, {}).get(s.id)
            values.append(value)
            if value is not None:
                filled_cells += 1
                pairs.append((value, ev.coefficient or 1))
        rows.append(
            {
                "name": f"{s.last_name} {s.first_name}".strip(),
                "enrollment_number": getattr(s, "enrollment_number", None) or "",
                "values": values,
                "average": _weighted_average(pairs),
            }
        )
    _assign_ranks(rows)
    return rows, filled_cells


def _class_stats(
    rows: list[dict[str, Any]], student_count: int, eval_count: int, filled_cells: int
) -> dict[str, Any]:
    averages = [r["average"] for r in rows if r["average"] is not None]
    if averages:
        mean = sum(averages) / Decimal(len(averages))
        class_avg = mean.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        min_avg = min(averages)
        max_avg = max(averages)
    else:
        class_avg = min_avg = max_avg = None
    total_cells = student_count * eval_count
    fill_rate = round(100 * filled_cells / total_cells) if total_cells else 0
    return {
        "class_avg": class_avg,
        "min": min_avg,
        "max": max_avg,
        "fill_rate": fill_rate,
    }


async def _resolve_subject_name(
    db: AsyncSession, evaluations: list[Evaluation], subject_id: int
) -> str:
    for ev in evaluations:
        if ev.subject is not None:
            return ev.subject.name
    subject = await db.get(Subject, subject_id)
    return subject.name if subject else ""


async def get_grade_report_pdf(
    db: AsyncSession,
    class_id: int,
    subject_id: int,
    trimester: int,
    academic_year_id: int,
) -> bytes:
    """Génère le relevé de notes PDF d'une (classe, matière, trimestre, année)."""
    klass = await _load_class(db, class_id)

    all_evals = await grades_repository.list_evaluations(
        db,
        class_id=class_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )
    evaluations = sorted(
        (ev for ev in all_evals if ev.subject_id == subject_id),
        key=lambda ev: ev.date,
    )

    students = await reports_repository.get_enrolled_students(db, class_id, academic_year_id)
    student_rows, filled_cells = _build_student_rows(students, evaluations)
    class_stats = _class_stats(student_rows, len(students), len(evaluations), filled_cells)

    subject_name = await _resolve_subject_name(db, evaluations, subject_id)
    ay = await db.get(AcademicYear, academic_year_id)
    class_info = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
    }

    evaluations_payload = [
        {
            "title": ev.title,
            "type": ev.type,
            "coefficient": ev.coefficient,
            "date": ev.date,
        }
        for ev in evaluations
    ]

    school = await load_school_settings_for_pdf(db)
    return generate_grade_report_pdf(
        school,
        class_info,
        subject_name,
        f"Trimestre {trimester}",
        ay.name if ay else "",
        evaluations_payload,
        student_rows,
        class_stats,
    )
