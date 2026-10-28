"""Accès DB aux enseignants retenus par classe et par matière."""

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import Class, Subject
from app.models.class_subject_teacher import ClassSubjectTeacher
from app.models.subject_teacher import SubjectTeacher


async def explicit_teachers_for_class(db: AsyncSession, class_id: int) -> dict[int, int]:
    """subject_id -> teacher_id, pour les choix explicites de la classe."""
    stmt = select(ClassSubjectTeacher.subject_id, ClassSubjectTeacher.teacher_id).where(
        ClassSubjectTeacher.class_id == class_id
    )
    return dict((await db.execute(stmt)).all())


async def explicit_teachers_for_subjects(
    db: AsyncSession, subject_ids: Iterable[int]
) -> dict[tuple[int, int], int]:
    """(class_id, subject_id) -> teacher_id, pour les matières données, toutes classes."""
    ids = list(subject_ids)
    if not ids:
        return {}
    stmt = select(
        ClassSubjectTeacher.class_id, ClassSubjectTeacher.subject_id, ClassSubjectTeacher.teacher_id
    ).where(ClassSubjectTeacher.subject_id.in_(ids))
    return {(cid, sid): tid for cid, sid, tid in (await db.execute(stmt)).all()}


async def set_class_teacher(
    db: AsyncSession, class_id: int, subject_id: int, teacher_id: int | None
) -> None:
    """Pose le choix explicite, ou le retire si `teacher_id` est None. Ne commite pas."""
    row = (
        await db.execute(
            select(ClassSubjectTeacher).where(
                ClassSubjectTeacher.class_id == class_id,
                ClassSubjectTeacher.subject_id == subject_id,
            )
        )
    ).scalar_one_or_none()
    if teacher_id is None:
        if row is not None:
            await db.delete(row)
        return
    if row is None:
        db.add(ClassSubjectTeacher(class_id=class_id, subject_id=subject_id, teacher_id=teacher_id))
    else:
        row.teacher_id = teacher_id
    await db.flush()


async def purge_orphan_teachers(
    db: AsyncSession, subject_id: int, kept_teacher_ids: list[int]
) -> None:
    """Retire les choix de la matière dont l'enseignant n'est plus retenu pour elle."""
    stmt = delete(ClassSubjectTeacher).where(ClassSubjectTeacher.subject_id == subject_id)
    if kept_teacher_ids:
        stmt = stmt.where(ClassSubjectTeacher.teacher_id.not_in(kept_teacher_ids))
    await db.execute(stmt)


async def classes_for_levels(db: AsyncSession, level_ids: Iterable[int]) -> list[Class]:
    ids = list(level_ids)
    if not ids:
        return []
    return list((await db.execute(select(Class).where(Class.level_id.in_(ids)))).scalars().all())


async def subjects_taught_by(db: AsyncSession, teacher_id: int) -> list[Subject]:
    """Matières où l'enseignant est retenu, avec la liste complète de leurs enseignants."""
    retenues = select(SubjectTeacher.subject_id).where(SubjectTeacher.teacher_id == teacher_id)
    stmt = (
        select(Subject)
        .where(Subject.id.in_(retenues))
        .options(selectinload(Subject.teacher_links))
        .order_by(Subject.id)
    )
    return list((await db.execute(stmt)).scalars().all())
