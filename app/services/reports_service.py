"""Service reports — generation des bulletins scolaires trimestriels."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import SchoolSettings
from app.models.grade import Bulletin, CouncilDecision, Mention
from app.repositories import reports_repository as repo
from app.schemas.reports import (
    BulletinGenerateResponse,
    BulletinListResponse,
    BulletinResponse,
    SubjectAverageResponse,
)
from app.services.pdf_service import generate_bulletin_pdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_mention(avg: Decimal | None) -> str | None:
    if avg is None:
        return None
    if avg >= 16:
        return Mention.TRES_BIEN.value
    if avg >= 14:
        return Mention.BIEN.value
    if avg >= 12:
        return Mention.ASSEZ_BIEN.value
    if avg >= 10:
        return Mention.PASSABLE.value
    return Mention.MEDIOCRE.value


def _compute_council_decision(mga: Decimal | None) -> str | None:
    """Determine la decision du conseil de classe (trimestre 3 uniquement)."""
    if mga is None:
        return None
    if mga >= 10:
        return CouncilDecision.PASSAGE.value
    if mga >= Decimal("9.5"):
        return CouncilDecision.REPECHAGE.value
    if mga >= Decimal("8.5"):
        return CouncilDecision.REDOUBLEMENT.value
    return CouncilDecision.EXCLUSION.value


def _student_full_name(student: Any) -> str:
    return f"{student.first_name} {student.last_name}"


def _bulletin_to_response(bulletin: Bulletin, total_students: int) -> BulletinResponse:
    subject_avgs = [
        SubjectAverageResponse(
            subject_id=sa.subject_id,
            subject_name=sa.subject.name if sa.subject else "",
            average=sa.average,
            coefficient=sa.coefficient,
        )
        for sa in (bulletin.subject_averages or [])
    ]
    return BulletinResponse(
        id=bulletin.id,
        student_id=bulletin.student_id,
        student_name=_student_full_name(bulletin.student) if bulletin.student else "",
        class_id=bulletin.class_id,
        class_name=bulletin.class_.name if bulletin.class_ else "",
        academic_year_id=bulletin.academic_year_id,
        trimester=bulletin.trimester,
        average=bulletin.average,
        rank=bulletin.rank,
        total_students=total_students,
        mention=bulletin.mention,
        teacher_comment=bulletin.teacher_comment,
        council_decision=bulletin.council_decision,
        file_url=bulletin.file_url,
        generated_at=bulletin.generated_at,
        is_published=bulletin.is_published,
        subject_averages=subject_avgs,
        created_at=bulletin.created_at,
        updated_at=bulletin.updated_at,
    )


# ---------------------------------------------------------------------------
# Generate bulletins
# ---------------------------------------------------------------------------


async def generate_bulletins(
    db: AsyncSession,
    *,
    class_id: int,
    trimester: int,
    academic_year_id: int,
    generated_by: int,
) -> BulletinGenerateResponse:
    """Genere les bulletins pour tous les eleves d'une classe/trimestre."""
    # 1. Recuperer les eleves inscrits
    students = await repo.get_enrolled_students(db, class_id, academic_year_id)
    if not students:
        raise BusinessValidationError(
            f"No enrolled students found for class {class_id} / year {academic_year_id}"
        )

    # 2. Recuperer les evaluations du trimestre
    evaluations = await repo.get_evaluations_for_class_trimester(
        db, class_id, trimester, academic_year_id
    )
    if not evaluations:
        raise BusinessValidationError(
            f"No evaluations found for class {class_id} / trimester {trimester}"
        )

    eval_map = {e.id: e for e in evaluations}
    eval_ids = list(eval_map.keys())

    # 3. Recuperer toutes les notes saisies
    grades = await repo.get_entered_grades_for_evaluations(db, eval_ids)

    # 4. Calculer les moyennes par matiere pour chaque eleve
    # Structure: {student_id: {subject_id: [(grade_value, eval_coefficient)]}}
    student_subject_grades: dict[int, dict[int, list[tuple[Decimal, int]]]] = {}
    for g in grades:
        if g.value is None:
            continue
        ev = eval_map.get(g.evaluation_id)
        if ev is None:
            continue
        student_subject_grades.setdefault(g.student_id, {}).setdefault(ev.subject_id, []).append(
            (g.value, ev.coefficient)
        )

    # Subject coefficient map
    subject_coeff_map: dict[int, int] = {}
    for ev in evaluations:
        if ev.subject and ev.subject_id not in subject_coeff_map:
            subject_coeff_map[ev.subject_id] = ev.subject.coefficient

    # Subject name map for later
    subject_name_map: dict[int, str] = {}
    for ev in evaluations:
        if ev.subject and ev.subject_id not in subject_name_map:
            subject_name_map[ev.subject_id] = ev.subject.name

    # 5. Pour chaque eleve: calculer moyenne matiere, puis moyenne trimestrielle
    student_averages: dict[int, Decimal | None] = {}
    student_subject_avgs: dict[int, dict[int, Decimal]] = {}

    for student in students:
        sid = student.id
        subj_grades = student_subject_grades.get(sid, {})
        if not subj_grades:
            student_averages[sid] = None
            continue

        weighted_sum = Decimal("0")
        total_coeff = 0
        subj_avgs: dict[int, Decimal] = {}

        for subject_id, grade_pairs in subj_grades.items():
            # Subject average = sum(grade * eval_coeff) / sum(eval_coeff)
            numerator = sum(Decimal(str(v)) * c for v, c in grade_pairs)
            denominator = sum(c for _, c in grade_pairs)
            if denominator == 0:
                continue
            subject_avg = _quantize(numerator / denominator)
            subj_avgs[subject_id] = subject_avg

            # Weighted by subject coefficient for trimester average
            s_coeff = subject_coeff_map.get(subject_id, 1)
            weighted_sum += subject_avg * s_coeff
            total_coeff += s_coeff

        student_subject_avgs[sid] = subj_avgs

        if total_coeff > 0:
            student_averages[sid] = _quantize(weighted_sum / total_coeff)
        else:
            student_averages[sid] = None

    # 6. Ranking (competition ranking: ex-aequo share same rank)
    ranked = sorted(
        [(sid, avg) for sid, avg in student_averages.items() if avg is not None],
        key=lambda x: x[1],
        reverse=True,
    )
    student_ranks: dict[int, int | None] = {s.id: None for s in students}
    rank = 1
    for i, (sid, avg) in enumerate(ranked):
        if i > 0 and avg == ranked[i - 1][1]:
            student_ranks[sid] = student_ranks[ranked[i - 1][0]]
        else:
            student_ranks[sid] = rank
        rank = i + 2

    total_students = len(students)

    # 7. For trimester 3: compute MGA and council decision
    # MGA = (T1*1 + T2*2 + T3*2) / 5
    mga_map: dict[int, Decimal | None] = {}
    council_decisions: dict[int, str | None] = {}
    if trimester == 3:
        for student in students:
            sid = student.id
            t3_avg = student_averages.get(sid)
            if t3_avg is None:
                mga_map[sid] = None
                council_decisions[sid] = None
                continue

            # Fetch T1 and T2 bulletins
            t1_bulletin = await repo.get_bulletin(db, sid, class_id, academic_year_id, 1)
            t2_bulletin = await repo.get_bulletin(db, sid, class_id, academic_year_id, 2)

            t1_avg = (
                t1_bulletin.average if t1_bulletin and t1_bulletin.average is not None else None
            )
            t2_avg = (
                t2_bulletin.average if t2_bulletin and t2_bulletin.average is not None else None
            )

            if t1_avg is not None and t2_avg is not None:
                mga = _quantize((t1_avg * 1 + t2_avg * 2 + t3_avg * 2) / 5)
                mga_map[sid] = mga
                council_decisions[sid] = _compute_council_decision(mga)
            else:
                mga_map[sid] = None
                council_decisions[sid] = None

    # 8. Create/update bulletins and subject averages in a transaction
    async with db.begin_nested():
        bulletin_ids: list[int] = []
        for student in students:
            sid = student.id
            avg = student_averages.get(sid)
            mention = _compute_mention(avg)
            decision = council_decisions.get(sid) if trimester == 3 else None

            bulletin = await repo.upsert_bulletin(
                db,
                student_id=sid,
                class_id=class_id,
                academic_year_id=academic_year_id,
                trimester=trimester,
                average=avg,
                rank=student_ranks.get(sid),
                mention=mention,
                council_decision=decision,
            )
            bulletin.generated_at = datetime.utcnow()
            bulletin_ids.append(bulletin.id)

            # Delete existing subject averages and recreate
            await repo.delete_subject_averages_for_bulletin(db, bulletin.id)

            subj_avgs = student_subject_avgs.get(sid, {})
            for subject_id, subject_avg in subj_avgs.items():
                await repo.create_subject_average(
                    db,
                    bulletin_id=bulletin.id,
                    subject_id=subject_id,
                    student_id=sid,
                    trimester=trimester,
                    average=subject_avg,
                    coefficient=subject_coeff_map.get(subject_id, 1),
                )

        await audit_log(
            db,
            entity_type="bulletin",
            action=AuditAction.CREATE,
            user_id=generated_by,
            notes=f"Generated {len(bulletin_ids)} bulletins for class {class_id} T{trimester}",
            new_values={"class_id": class_id, "trimester": trimester, "count": len(bulletin_ids)},
        )

    await db.commit()

    # 9. Reload bulletins with relations for response
    bulletins = await repo.list_bulletins_for_class(db, class_id, trimester, academic_year_id)
    return BulletinGenerateResponse(
        message=f"Generated {len(bulletins)} bulletins for trimester {trimester}",
        generated=len(bulletins),
        bulletins=[_bulletin_to_response(b, total_students) for b in bulletins],
    )


# ---------------------------------------------------------------------------
# List bulletins
# ---------------------------------------------------------------------------


async def list_bulletins(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> BulletinListResponse:
    """Liste les bulletins generes pour une classe/trimestre."""
    bulletins = await repo.list_bulletins_for_class(db, class_id, trimester, academic_year_id)
    total_students = await repo.count_enrolled_students(db, class_id, academic_year_id)
    return BulletinListResponse(
        items=[_bulletin_to_response(b, total_students) for b in bulletins],
        total=len(bulletins),
    )


# ---------------------------------------------------------------------------
# Get bulletin PDF
# ---------------------------------------------------------------------------


async def _get_school_settings(db: AsyncSession) -> dict[str, Any]:
    """Fetch the singleton SchoolSettings row."""
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement", "ministry_code": None}
    return {
        "school_name": settings.school_name,
        "ministry_code": settings.ministry_code,
        "address": settings.address,
        "phone": settings.phone,
    }


async def get_bulletin_pdf(db: AsyncSession, bulletin_id: int) -> bytes:
    """Generate and return the PDF bytes of a bulletin."""
    bulletin = await repo.get_bulletin_by_id(db, bulletin_id)
    if bulletin is None:
        raise NotFoundError("Bulletin", bulletin_id)

    total_students = await repo.count_enrolled_students(
        db, bulletin.class_id, bulletin.academic_year_id
    )
    school = await _get_school_settings(db)

    subject_averages = [
        {
            "subject_name": sa.subject.name if sa.subject else "",
            "average": sa.average,
            "coefficient": sa.coefficient,
        }
        for sa in (bulletin.subject_averages or [])
    ]

    bulletin_data = {
        "student_name": _student_full_name(bulletin.student) if bulletin.student else "",
        "class_name": bulletin.class_.name if bulletin.class_ else "",
        "trimester": bulletin.trimester,
        "academic_year_name": bulletin.academic_year.name if bulletin.academic_year else "",
        "average": bulletin.average,
        "rank": bulletin.rank,
        "total_students": total_students,
        "mention": bulletin.mention,
        "council_decision": bulletin.council_decision,
        "teacher_comment": bulletin.teacher_comment,
        "subject_averages": subject_averages,
        "generated_at": bulletin.generated_at,
    }

    return generate_bulletin_pdf(bulletin_data, school)


# ---------------------------------------------------------------------------
# Publish bulletins
# ---------------------------------------------------------------------------


async def publish_bulletins(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
    *,
    published_by: int,
) -> int:
    """Set is_published=True for all bulletins of a class/trimester and notify parents."""
    from sqlalchemy import update as sql_update

    stmt = (
        sql_update(Bulletin)
        .where(
            Bulletin.class_id == class_id,
            Bulletin.trimester == trimester,
            Bulletin.academic_year_id == academic_year_id,
            not Bulletin.is_published,
        )
        .values(is_published=True)
    )
    result = await db.execute(stmt)
    await db.commit()
    count = result.rowcount

    # Dispatch notifications to parents (background, best-effort)
    if count > 0:
        try:
            from app.models.notification import NotificationType
            from app.services import notification_dispatch_service as notif

            bulletins = await repo.list_bulletins_for_class(
                db, class_id, trimester, academic_year_id
            )
            for b in bulletins:
                if b.student and b.student.user_id:
                    await notif.dispatch_notification(
                        db,
                        user_id=b.student.user_id,
                        notification_type=NotificationType.BULLETIN_PUBLISHED,
                        context={
                            "student_name": f"{b.student.first_name} {b.student.last_name}",
                            "trimester": str(trimester),
                            "title": "Bulletin publié",
                            "body": f"Le bulletin du trimestre {trimester} est disponible.",
                        },
                    )
        except Exception:
            logger.exception("Failed to dispatch bulletin notifications")

    return count
