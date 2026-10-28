"""Enseignants d'une matière : liste ordonnée, validée et synchronisée.

`subjects.teacher_id` suit toujours le premier enseignant de la liste, pour les
lecteurs qui n'ont pas encore migré (voir la migration 0087).
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.academic import Subject
from app.models.subject_teacher import SubjectTeacher
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile
from app.schemas.subject_teachers import SubjectSlotCount, SubjectSlotCountsResponse

MAX_TEACHERS_PER_SUBJECT = 30


def requested_teacher_ids(
    teacher_ids: list[int] | None, teacher_id: int | None
) -> list[int] | None:
    """Liste demandée par le client, ou None si la requête ne touche pas aux enseignants.

    `teacher_ids` prime. L'ancien champ `teacher_id` reste accepté comme liste d'un seul élément.
    """
    if teacher_ids is not None:
        return teacher_ids
    if teacher_id is not None:
        return [teacher_id]
    return None


async def set_subject_teachers(db: AsyncSession, subject: Subject, teacher_ids: list[int]) -> None:
    """Remplace les enseignants de la matière par `teacher_ids`, dans cet ordre.

    Ne commite pas : l'appelant garde la transaction.
    """
    ordered = list(dict.fromkeys(teacher_ids))
    if len(ordered) > MAX_TEACHERS_PER_SUBJECT:
        raise BusinessValidationError(
            f"Une matière ne peut pas avoir plus de {MAX_TEACHERS_PER_SUBJECT} enseignants."
        )
    if ordered:
        found = set(
            (await db.execute(select(TeacherProfile.id).where(TeacherProfile.id.in_(ordered))))
            .scalars()
            .all()
        )
        missing = [tid for tid in ordered if tid not in found]
        if missing:
            ids = ", ".join(str(tid) for tid in missing)
            raise BusinessValidationError(f"Enseignant(s) introuvable(s) : {ids}.")

    await db.execute(delete(SubjectTeacher).where(SubjectTeacher.subject_id == subject.id))
    db.add_all(
        [
            SubjectTeacher(subject_id=subject.id, teacher_id=tid, position=index)
            for index, tid in enumerate(ordered)
        ]
    )
    subject.teacher_id = ordered[0] if ordered else None
    await db.flush()


async def replace_subject_teachers_audited(
    db: AsyncSession, subject: Subject, teacher_ids: list[int], *, actor: int
) -> None:
    """Comme `set_subject_teachers`, et journalise l'ancienne et la nouvelle liste.

    `subject.teacher_links` doit être chargé par l'appelant.
    """
    avant = [link.teacher_id for link in subject.teacher_links]
    apres = list(dict.fromkeys(teacher_ids))
    if avant == apres:
        return
    async with db.begin_nested():
        await set_subject_teachers(db, subject, apres)
        await audit_log(
            db,
            entity_type="subject",
            action=AuditAction.UPDATE,
            user_id=actor,
            entity_id=subject.id,
            old_values={"teacher_ids": avant},
            new_values={"teacher_ids": apres},
            subject_label=subject.name,
        )


async def count_slots_by_teacher(db: AsyncSession, subject_id: int) -> dict[int, int]:
    """Nombre de créneaux de l'emploi du temps par enseignant, pour une matière."""
    stmt = (
        select(TimetableSlot.teacher_id, func.count(TimetableSlot.id))
        .where(TimetableSlot.subject_id == subject_id)
        .group_by(TimetableSlot.teacher_id)
    )
    rows = (await db.execute(stmt)).all()
    return {int(teacher_id): int(total) for teacher_id, total in rows}


async def slot_counts_for_subject(db: AsyncSession, subject_id: int) -> SubjectSlotCountsResponse:
    if await db.get(Subject, subject_id) is None:
        raise NotFoundError("Subject", subject_id)
    counts = await count_slots_by_teacher(db, subject_id)
    return SubjectSlotCountsResponse(
        counts=[
            SubjectSlotCount(teacher_id=teacher_id, slots=slots)
            for teacher_id, slots in sorted(counts.items())
        ]
    )
