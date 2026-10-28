"""Accès DB aux enseignants rattachés aux matières (table `subject_teachers`)."""

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import Subject
from app.models.subject_teacher import SubjectTeacher
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile


async def find_existing_teacher_ids(db: AsyncSession, teacher_ids: list[int]) -> set[int]:
    stmt = select(TeacherProfile.id).where(TeacherProfile.id.in_(teacher_ids))
    return set((await db.execute(stmt)).scalars().all())


async def list_teacher_ids(db: AsyncSession, subject_id: int) -> list[int]:
    stmt = (
        select(SubjectTeacher.teacher_id)
        .where(SubjectTeacher.subject_id == subject_id)
        .order_by(SubjectTeacher.position, SubjectTeacher.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def delete_links(db: AsyncSession, subject_id: int) -> None:
    await db.execute(delete(SubjectTeacher).where(SubjectTeacher.subject_id == subject_id))


async def add_links(db: AsyncSession, subject_id: int, ordered_ids: list[int]) -> None:
    db.add_all(
        [
            SubjectTeacher(subject_id=subject_id, teacher_id=tid, position=index)
            for index, tid in enumerate(ordered_ids)
        ]
    )


async def count_slots_by_teacher(db: AsyncSession, subject_id: int) -> list[tuple[int, int]]:
    """Créneaux de l'emploi du temps par enseignant, pour une matière, triés par identifiant."""
    stmt = (
        select(TimetableSlot.teacher_id, func.count(TimetableSlot.id))
        .where(TimetableSlot.subject_id == subject_id)
        .group_by(TimetableSlot.teacher_id)
        .order_by(TimetableSlot.teacher_id)
    )
    rows = (await db.execute(stmt)).all()
    return [(int(tid), int(total)) for tid, total in rows]


async def count_instances_without_teacher(db: AsyncSession) -> int:
    """Matières d'un niveau (instances) sans aucun enseignant rattaché."""
    stmt = select(func.count(Subject.id)).where(
        Subject.level_id.isnot(None),
        ~exists().where(SubjectTeacher.subject_id == Subject.id),
    )
    return int((await db.execute(stmt)).scalar() or 0)


async def subject_ids_for_teacher(db: AsyncSession, teacher_id: int) -> list[int]:
    stmt = select(SubjectTeacher.subject_id).where(SubjectTeacher.teacher_id == teacher_id)
    return list((await db.execute(stmt)).scalars().all())


async def delete_links_for_teacher(db: AsyncSession, teacher_id: int) -> None:
    await db.execute(delete(SubjectTeacher).where(SubjectTeacher.teacher_id == teacher_id))


async def resync_first_teacher(db: AsyncSession, subject_ids: list[int]) -> None:
    """Remet `subjects.teacher_id` sur le premier enseignant restant (ou NULL)."""
    if not subject_ids:
        return
    rows = await db.execute(
        select(SubjectTeacher.subject_id, SubjectTeacher.teacher_id)
        .where(SubjectTeacher.subject_id.in_(subject_ids))
        .order_by(SubjectTeacher.subject_id, SubjectTeacher.position, SubjectTeacher.id)
    )
    first: dict[int, int] = {}
    for subject_id, teacher_id in rows.all():
        first.setdefault(subject_id, teacher_id)
    subjects = await db.execute(select(Subject).where(Subject.id.in_(subject_ids)))
    for subject in subjects.scalars().all():
        subject.teacher_id = first.get(subject.id)
        db.expire(subject, ["teacher_links"])
    await db.flush()
