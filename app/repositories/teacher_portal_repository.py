"""Repository portail enseignant — accès DB read-only pour le teacher portal."""

from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.academic import Class, Level, Subject
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Evaluation, Grade
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile


async def get_teacher_by_user_id(db: AsyncSession, user_id: int) -> TeacherProfile | None:
    """Retourne le profil enseignant associé à un user_id."""
    stmt = select(TeacherProfile).where(TeacherProfile.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_teacher_classes(db: AsyncSession, teacher_id: int) -> list[dict]:
    """Retourne les classes distinctes assignées à un enseignant via timetable_slots."""
    stmt = (
        select(
            TimetableSlot.class_id,
            Class.name.label("class_name"),
            Level.name.label("level_name"),
            Subject.name.label("subject_name"),
            TimetableSlot.subject_id,
        )
        .join(Class, TimetableSlot.class_id == Class.id)
        .join(Level, Class.level_id == Level.id)
        .join(Subject, TimetableSlot.subject_id == Subject.id)
        .where(TimetableSlot.teacher_id == teacher_id)
        .distinct()
        .order_by(Class.name, Subject.name)
    )
    rows = (await db.execute(stmt)).all()

    results = []
    for row in rows:
        count_stmt = (
            select(func.count())
            .select_from(Enrollment)
            .where(
                Enrollment.class_id == row.class_id,
                Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
            )
        )
        student_count = (await db.execute(count_stmt)).scalar() or 0
        results.append(
            {
                "class_id": row.class_id,
                "class_name": row.class_name,
                "level_name": row.level_name,
                "subject_name": row.subject_name,
                "student_count": student_count,
            }
        )

    return results


async def get_teacher_schedule(db: AsyncSession, teacher_id: int) -> list[TimetableSlot]:
    """Retourne les créneaux emploi du temps d'un enseignant."""
    stmt = (
        select(TimetableSlot)
        .where(TimetableSlot.teacher_id == teacher_id)
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.class_),
            selectinload(TimetableSlot.room),
        )
        .order_by(TimetableSlot.day, TimetableSlot.start_time)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_distinct_classes(db: AsyncSession, teacher_id: int) -> int:
    """Compte les classes distinctes assignées à un enseignant."""
    stmt = select(func.count(distinct(TimetableSlot.class_id))).where(
        TimetableSlot.teacher_id == teacher_id
    )
    return (await db.execute(stmt)).scalar() or 0


async def count_total_students(db: AsyncSession, teacher_id: int) -> int:
    """Compte le nombre total d'élèves dans les classes de l'enseignant."""
    class_ids_stmt = select(distinct(TimetableSlot.class_id)).where(
        TimetableSlot.teacher_id == teacher_id
    )
    stmt = (
        select(func.count())
        .select_from(Enrollment)
        .where(
            Enrollment.class_id.in_(class_ids_stmt),
            Enrollment.status.not_in([EnrollmentStatus.ANNULE, EnrollmentStatus.REJETE]),
        )
    )
    return (await db.execute(stmt)).scalar() or 0


async def count_upcoming_evaluations(db: AsyncSession, teacher_id: int) -> int:
    """Compte les évaluations à venir pour cet enseignant."""
    today = date.today()
    stmt = (
        select(func.count())
        .select_from(Evaluation)
        .where(
            Evaluation.teacher_id == teacher_id,
            Evaluation.date > today,
        )
    )
    return (await db.execute(stmt)).scalar() or 0


async def list_upcoming_evaluations(
    db: AsyncSession,
    teacher_id: int,
    *,
    limit: int = 5,
) -> list[dict]:
    """Liste les évaluations récentes ou à venir pour le dashboard.

    Inclut date >= today - 7 days pour montrer aussi les évals récentes
    qui peuvent encore avoir des notes à saisir. Joint avec class + subject
    pour l'affichage et compte les notes saisies.
    """
    cutoff = date.today() - timedelta(days=7)
    stmt = (
        select(Evaluation)
        .options(
            selectinload(Evaluation.class_),
            selectinload(Evaluation.subject),
            selectinload(Evaluation.grades),
        )
        .where(
            Evaluation.teacher_id == teacher_id,
            Evaluation.date >= cutoff,
        )
        .order_by(Evaluation.date.asc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items: list[dict] = []
    for ev in rows:
        graded = sum(1 for g in (ev.grades or []) if g.value is not None)
        total = len(ev.grades or [])
        items.append(
            {
                "id": ev.id,
                "title": ev.title,
                "type": ev.type.value if hasattr(ev.type, "value") else str(ev.type),
                "date": ev.date.isoformat(),
                "class_name": ev.class_.name if ev.class_ else "",
                "subject_name": ev.subject.name if ev.subject else "",
                "graded_students": graded,
                "total_students": total,
            }
        )
    return items


async def get_next_course(db: AsyncSession, teacher_id: int) -> dict | None:
    """Retourne le prochain créneau d'enseignement (today/future).

    Le timetable est hebdomadaire — on cherche aujourd'hui après l'heure
    courante, sinon le 1er créneau du prochain jour de la semaine. Renvoie
    None si l'enseignant n'a aucun créneau planifié.
    """
    from datetime import datetime

    now = datetime.now()
    today_name = _DAY_INDEX_TO_NAME.get(now.weekday())
    current_time = now.time()

    # 1) Slot aujourd'hui après l'heure courante
    if today_name is not None:
        stmt_today = (
            select(TimetableSlot)
            .options(
                selectinload(TimetableSlot.subject),
                selectinload(TimetableSlot.class_),
                selectinload(TimetableSlot.room),
            )
            .where(
                TimetableSlot.teacher_id == teacher_id,
                TimetableSlot.day == today_name,
                TimetableSlot.start_time > current_time,
            )
            .order_by(TimetableSlot.start_time.asc())
            .limit(1)
        )
        slot = (await db.execute(stmt_today)).scalar_one_or_none()
        if slot is not None:
            return _slot_to_dict(slot)

    # 2) Sinon premier slot du prochain jour de la semaine où le prof enseigne
    stmt_any = (
        select(TimetableSlot)
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.class_),
            selectinload(TimetableSlot.room),
        )
        .where(TimetableSlot.teacher_id == teacher_id)
        .order_by(TimetableSlot.day.asc(), TimetableSlot.start_time.asc())
        .limit(1)
    )
    slot = (await db.execute(stmt_any)).scalar_one_or_none()
    return _slot_to_dict(slot) if slot is not None else None


_DAY_INDEX_TO_NAME = {
    0: "lundi",
    1: "mardi",
    2: "mercredi",
    3: "jeudi",
    4: "vendredi",
    5: "samedi",
    6: "dimanche",
}


def _slot_to_dict(slot: TimetableSlot) -> dict:
    return {
        "subject_name": slot.subject.name if slot.subject else "",
        "class_name": slot.class_.name if slot.class_ else "",
        "start_time": slot.start_time.strftime("%H:%M"),
        "end_time": slot.end_time.strftime("%H:%M"),
        "room": slot.room.name if slot.room else None,
    }


async def get_class_averages(db: AsyncSession, teacher_id: int) -> list[dict]:
    """Calcule la moyenne par classe/matière pour les évaluations de l'enseignant."""
    stmt = (
        select(
            Evaluation.class_id,
            Class.name.label("class_name"),
            Subject.name.label("subject_name"),
            func.avg(Grade.value).label("average"),
        )
        .join(Grade, Grade.evaluation_id == Evaluation.id)
        .join(Class, Evaluation.class_id == Class.id)
        .join(Subject, Evaluation.subject_id == Subject.id)
        .where(Evaluation.teacher_id == teacher_id)
        .group_by(Evaluation.class_id, Class.name, Subject.name)
        .order_by(Class.name, Subject.name)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "class_id": row.class_id,
            "class_name": row.class_name,
            "subject_name": row.subject_name,
            "average": round(float(row.average), 2) if row.average is not None else None,
        }
        for row in rows
    ]
