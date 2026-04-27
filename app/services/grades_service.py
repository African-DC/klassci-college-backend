"""Service notes — logique métier pour évaluations, notes et bulletins."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import NotFoundError
from app.models.grade import Evaluation
from app.models.user import TeacherProfile
from app.repositories import grades_repository as repo
from app.schemas.grades import (
    BulletinGenerateResponse,
    EvaluationCreate,
    GradeBatchUpdate,
)
from app.services.curriculum_service import validate_subject_class_pair

logger = logging.getLogger(__name__)


def _build_eval_response(ev: Evaluation, actor_user_id: int | None = None) -> dict[str, Any]:
    teacher_name = f"{ev.teacher.first_name} {ev.teacher.last_name}" if ev.teacher else ""
    total = len(ev.grades) if ev.grades is not None else 0
    graded = sum(1 for g in (ev.grades or []) if g.status == "entered")
    return {
        "id": ev.id,
        "title": ev.title,
        "type": ev.type,
        "date": ev.date,
        "coefficient": ev.coefficient,
        "subject_id": ev.subject_id,
        "subject_name": ev.subject.name if ev.subject else "",
        "class_id": ev.class_id,
        "class_name": ev.class_.name if ev.class_ else "",
        "teacher_id": ev.teacher_id,
        "teacher_name": teacher_name,
        "academic_year_id": ev.academic_year_id,
        "trimester": ev.trimester,
        "total_students": total,
        "graded_students": graded,
        "created_at": ev.created_at,
    }


async def list_evaluations(
    db: AsyncSession,
    *,
    class_id: int | None = None,
    teacher_id: int | None = None,
    academic_year_id: int | None = None,
    trimester: int | None = None,
) -> list[dict[str, Any]]:
    evals = await repo.list_evaluations(
        db,
        class_id=class_id,
        teacher_id=teacher_id,
        academic_year_id=academic_year_id,
        trimester=trimester,
    )
    return [_build_eval_response(ev) for ev in evals]


async def teacher_exists(db: AsyncSession, teacher_id: int) -> bool:
    """Vérifie qu'un teacher_profile existe — utilisé pour valider la délégation admin."""
    result = await db.execute(select(exists().where(TeacherProfile.id == teacher_id)))
    return bool(result.scalar())


async def create_evaluation(
    db: AsyncSession,
    data: EvaluationCreate,
    teacher_id: int,
    current_user_id: int,
) -> dict[str, Any]:
    # Fail-fast : refuser une paire (class_id, subject_id) incohérente avant toute
    # autre lecture/écriture. Utilise le même prédicat que le filtre Subject côté UI,
    # garantissant qu'une matière visible dans le Select ne sera jamais rejetée ici.
    await validate_subject_class_pair(db, data.class_id, data.subject_id)

    students = await repo.get_students_for_class(db, data.class_id, data.academic_year_id)

    eval_data = data.model_dump()
    eval_data["teacher_id"] = teacher_id

    evaluation = await repo.create_evaluation(db, data=eval_data, students=students)

    await audit_log(
        db,
        user_id=current_user_id,
        entity_type="evaluation",
        entity_id=evaluation.id,
        action=AuditAction.CREATE,
        old_values=None,
        new_values=eval_data,
    )

    await db.commit()

    # Recharger avec relations
    full_eval = await repo.get_evaluation_by_id(db, evaluation.id)
    if not full_eval:
        raise NotFoundError("Evaluation", evaluation.id)

    return _build_eval_response(full_eval)


async def get_grades(db: AsyncSession, eval_id: int) -> list[dict[str, Any]]:
    evaluation = await repo.get_evaluation_by_id(db, eval_id)
    if not evaluation:
        raise NotFoundError("Evaluation", eval_id)

    grades = await repo.get_grades_for_evaluation(db, eval_id)
    return [
        {
            "student_id": g.student_id,
            "student_name": f"{g.student.first_name} {g.student.last_name}" if g.student else "",
            "value": g.value,
            "status": g.status,
        }
        for g in grades
    ]


async def batch_update_grades(
    db: AsyncSession,
    eval_id: int,
    payload: GradeBatchUpdate,
    current_user_id: int,
) -> list[dict[str, Any]]:
    evaluation = await repo.get_evaluation_by_id(db, eval_id)
    if not evaluation:
        raise NotFoundError("Evaluation", eval_id)

    entries = [{"student_id": e.student_id, "value": e.value} for e in payload.grades]

    # Valider que tous les student_ids appartiennent bien à l'évaluation
    valid_student_ids = {g.student_id for g in evaluation.grades} if evaluation.grades else set()
    invalid_ids = [e["student_id"] for e in entries if e["student_id"] not in valid_student_ids]
    if invalid_ids:
        from app.core.exceptions import BusinessValidationError

        raise BusinessValidationError(f"Student IDs not enrolled in this evaluation: {invalid_ids}")

    grades = await repo.batch_update_grades(
        db, eval_id, entries, entered_by_user_id=current_user_id
    )

    await audit_log(
        db,
        user_id=current_user_id,
        entity_type="grade",
        entity_id=eval_id,
        action=AuditAction.UPDATE,
        old_values=None,
        new_values={"grades": entries},
    )

    await db.commit()

    return [
        {
            "student_id": g.student_id,
            "student_name": f"{g.student.first_name} {g.student.last_name}" if g.student else "",
            "value": g.value,
            "status": g.status,
        }
        for g in grades
    ]


async def get_summary(
    db: AsyncSession,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> dict[str, Any]:
    data = await repo.get_grades_summary(db, class_id, trimester, academic_year_id)
    return {
        "class_id": class_id,
        "trimester": trimester,
        **data,
    }


async def generate_bulletins(
    tenant_id: str,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> BulletinGenerateResponse:
    from app.tasks.grades_tasks import generate_bulletins_task

    task = generate_bulletins_task.delay(
        tenant_id=tenant_id,
        class_id=class_id,
        trimester=trimester,
        academic_year_id=academic_year_id,
    )
    return BulletinGenerateResponse(task_id=task.id)
