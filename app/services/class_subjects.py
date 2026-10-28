"""Les matières d'une classe : la seule définition de « qui appartient à cette classe ».

Une matière est une instance (niveau, série). Une classe reçoit les matières de
son niveau ; si elle a une série, celles de sa série et les matières sans série.
Une classe sans série reçoit toutes les matières de son niveau.

Toute lecture qui raisonne « matières de la classe » doit passer par ici.
Un chantier séparé (#527) restreindra les classes sans série.
"""

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import Class, Subject
from app.models.subject_teacher import SubjectTeacher


def subjects_for_class_stmt(cls: Class) -> Select[tuple[Subject]]:
    """Requête des matières de la classe, avec série et enseignants chargés."""
    stmt = select(Subject).where(Subject.level_id == cls.level_id)
    if cls.series_id:
        stmt = stmt.where(or_(Subject.series_id == cls.series_id, Subject.series_id.is_(None)))
    return stmt.options(
        selectinload(Subject.series),
        selectinload(Subject.teacher_links).selectinload(SubjectTeacher.teacher),
    ).order_by(Subject.id)


async def subjects_for_class(db: AsyncSession, cls: Class) -> list[Subject]:
    """Les matières de la classe, dans l'ordre de leur identifiant."""
    return list((await db.execute(subjects_for_class_stmt(cls))).scalars().all())


def subject_applies_to_class(subject: Subject, cls: Class) -> bool:
    """La même règle que `subjects_for_class_stmt`, pour une matière déjà chargée."""
    if subject.level_id != cls.level_id:
        return False
    if cls.series_id:
        return subject.series_id in (cls.series_id, None)
    return True
