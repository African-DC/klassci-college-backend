"""Les couples (classe, matière) qu'un enseignant assure, selon la règle du projet.

Pour une matière où l'enseignant est retenu, la classe le résout si son choix
explicite le désigne, ou si c'est l'unique enseignant retenu de la matière.
La charge hebdomadaire et la portée d'enseignement lisent la même règle.
"""

from sqlalchemy import Select, and_, func, or_, select

from app.models.academic import Class, Subject
from app.models.class_subject_teacher import ClassSubjectTeacher
from app.models.subject_teacher import SubjectTeacher
from app.services.class_subjects import class_subject_condition


def resolved_class_subjects(teacher_id: int) -> Select[tuple[int, int, int]]:
    """Une ligne par (classe, matière) résolue vers l'enseignant, avec ses heures."""
    kept = select(SubjectTeacher.subject_id).where(SubjectTeacher.teacher_id == teacher_id)
    eligible_count = (
        select(func.count(SubjectTeacher.id))
        .where(SubjectTeacher.subject_id == Subject.id)
        .correlate(Subject)
        .scalar_subquery()
    )
    return (
        select(
            Class.id.label("class_id"),
            Subject.id.label("subject_id"),
            Subject.hours_per_week.label("hours"),
        )
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
