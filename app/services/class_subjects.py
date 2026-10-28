"""Les matières d'une classe : la seule définition de « qui appartient à cette classe ».

Une matière est une instance (niveau, série). Une classe reçoit les matières de
son niveau ; si elle a une série, celles de sa série et les matières sans série.
Une classe sans série reçoit toutes les matières de son niveau.

La règle n'existe qu'en SQL (`class_subject_condition`) : elle sert à une seule
classe comme à une jointure. Un chantier séparé (#527) restreindra les classes
sans série.
"""

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models.academic import Class, Subject
from app.models.subject_teacher import SubjectTeacher


def class_subject_condition(
    klass: type[Class] = Class, subject: type[Subject] = Subject
) -> ColumnElement[bool]:
    """Vrai quand la matière appartient à la classe. À utiliser en jointure ou sur une classe."""
    return and_(
        subject.level_id == klass.level_id,
        or_(
            klass.series_id.is_(None),
            subject.series_id == klass.series_id,
            subject.series_id.is_(None),
        ),
    )


def subjects_for_class_stmt(cls: Class) -> Select[tuple[Subject]]:
    """Requête des matières de la classe, avec série et enseignants chargés."""
    return (
        select(Subject)
        .select_from(Class)
        .join(Subject, class_subject_condition())
        .where(Class.id == cls.id)
        .options(
            selectinload(Subject.series),
            selectinload(Subject.teacher_links).selectinload(SubjectTeacher.teacher),
        )
        .order_by(Subject.id)
    )


async def subjects_for_class(db: AsyncSession, cls: Class) -> list[Subject]:
    """Les matières de la classe, dans l'ordre de leur identifiant."""
    return list((await db.execute(subjects_for_class_stmt(cls))).scalars().all())
