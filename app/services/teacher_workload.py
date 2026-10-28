"""Charge hebdomadaire d'un enseignant : les heures des matières résolues vers lui."""

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import Class, Subject
from app.models.class_subject_teacher import ClassSubjectTeacher
from app.models.subject_teacher import SubjectTeacher
from app.services.class_subjects import class_subject_condition


async def teacher_weekly_hours(db: AsyncSession, teacher_id: int) -> int:
    """Heures par semaine : chaque (classe, matière) résolue vers cet enseignant compte ses heures.

    Pour une matière où l'enseignant est retenu, la classe le résout si son choix
    explicite le désigne, ou si c'est l'unique enseignant retenu de la matière.
    Une seule requête : jointure classes / matières, choix explicites, effectif retenu.
    """
    kept = select(SubjectTeacher.subject_id).where(SubjectTeacher.teacher_id == teacher_id)
    eligible_count = (
        select(func.count(SubjectTeacher.id))
        .where(SubjectTeacher.subject_id == Subject.id)
        .correlate(Subject)
        .scalar_subquery()
    )
    stmt = (
        select(func.coalesce(func.sum(Subject.hours_per_week), 0))
        .select_from(Class)
        .join(Subject, class_subject_condition())
        .outerjoin(
            ClassSubjectTeacher,
            and_(
                ClassSubjectTeacher.class_id == Class.id,
                ClassSubjectTeacher.subject_id == Subject.id,
            ),
        )
        .where(
            Subject.id.in_(kept),
            or_(eligible_count == 1, ClassSubjectTeacher.teacher_id == teacher_id),
        )
    )
    return int((await db.execute(stmt)).scalar() or 0)
