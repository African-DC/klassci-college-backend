"""Accès DB aux enseignants retenus par classe et par matière."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.class_subject_teacher import ClassSubjectTeacher


async def explicit_teachers_for_class(db: AsyncSession, class_id: int) -> dict[int, int]:
    """subject_id -> teacher_id, pour les choix explicites de la classe."""
    stmt = select(ClassSubjectTeacher.subject_id, ClassSubjectTeacher.teacher_id).where(
        ClassSubjectTeacher.class_id == class_id
    )
    return dict((await db.execute(stmt)).all())


async def apply_class_teachers(
    db: AsyncSession, class_id: int, wanted: dict[int, int | None]
) -> None:
    """Applique les choix de la classe en une passe : retire ceux à None, pose les autres.

    Une seule lecture des lignes existantes, un seul flush. Ne commite pas.
    """
    existing = {
        row.subject_id: row
        for row in (
            await db.execute(
                select(ClassSubjectTeacher).where(ClassSubjectTeacher.class_id == class_id)
            )
        )
        .scalars()
        .all()
    }
    for subject_id, teacher_id in wanted.items():
        row = existing.get(subject_id)
        if teacher_id is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(
                ClassSubjectTeacher(class_id=class_id, subject_id=subject_id, teacher_id=teacher_id)
            )
        else:
            row.teacher_id = teacher_id
    await db.flush()


async def purge_orphan_teachers(
    db: AsyncSession, subject_id: int, kept_teacher_ids: list[int]
) -> dict[int, list[int]]:
    """Retire les choix de la matière dont l'enseignant n'est plus retenu pour elle.

    Rend, pour la matière, les classes dont le choix a été retiré. Ne commite pas.
    """
    cond = [ClassSubjectTeacher.subject_id == subject_id]
    if kept_teacher_ids:
        cond.append(ClassSubjectTeacher.teacher_id.not_in(kept_teacher_ids))
    return await _purge(db, cond)


async def purge_choices_of_teacher(db: AsyncSession, teacher_id: int) -> dict[int, list[int]]:
    """Retire tous les choix d'un enseignant, toutes matières confondues.

    Rend subject_id -> classes dont le choix a été retiré. Ne commite pas.
    """
    return await _purge(db, [ClassSubjectTeacher.teacher_id == teacher_id])


async def _purge(db: AsyncSession, cond: list[ColumnElement[bool]]) -> dict[int, list[int]]:
    rows = (
        await db.execute(
            select(ClassSubjectTeacher.subject_id, ClassSubjectTeacher.class_id).where(*cond)
        )
    ).all()
    if not rows:
        return {}
    await db.execute(delete(ClassSubjectTeacher).where(*cond))
    removed: dict[int, list[int]] = {}
    for subject_id, class_id in rows:
        removed.setdefault(subject_id, []).append(class_id)
    return removed
