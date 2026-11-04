"""Ce qu'un enseignant couvre à une date : ses classes, et celles qu'il remplace.

Trois sources, réunies en couples (classe, matière) :

- ses créneaux de l'emploi du temps de l'année en cours ;
- les classes où il est l'enseignant retenu d'une matière (`resolved_teaching`),
  même avant que l'emploi du temps soit généré ;
- pendant un congé approuvé dont il assure l'intérim, les couples de
  l'enseignant absent, calculés de la même façon.

Le portail enseignant lisait jusqu'ici les seuls créneaux, toutes années
confondues : un remplaçant ou un enseignant affecté sans emploi du temps se
voyait refuser sa classe, et un créneau de l'an dernier en ouvrait encore une.
Sans année en cours, aucun créneau ne compte : on refuse plutôt que d'ouvrir.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.leave import LeaveRequest, LeaveStatus
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile
from app.repositories.admin_repository import get_current_academic_year_id
from app.services.resolved_teaching import resolved_class_subjects


@dataclass(frozen=True)
class TeachingScope:
    teacher_id: int
    # (class_id, subject_id) : ce que l'enseignant assure, intérims compris.
    class_subjects: frozenset[tuple[int, int]]
    # Enseignants absents dont il assure l'intérim à la date du calcul.
    replaced_teacher_ids: frozenset[int]

    @property
    def class_ids(self) -> frozenset[int]:
        return frozenset(class_id for class_id, _ in self.class_subjects)

    def covers_class(self, class_id: int) -> bool:
        return class_id in self.class_ids


async def replaced_teachers(db: AsyncSession, teacher_id: int, on: date) -> frozenset[int]:
    """Les enseignants en congé approuvé à cette date dont il est l'intérimaire."""
    stmt = (
        select(TeacherProfile.id)
        .join(LeaveRequest, LeaveRequest.user_id == TeacherProfile.user_id)
        .where(
            LeaveRequest.interim_teacher_id == teacher_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= on,
            LeaveRequest.end_date >= on,
        )
    )
    return frozenset((await db.execute(stmt)).scalars().all())


async def _own_class_subjects(
    db: AsyncSession, teacher_id: int, academic_year_id: int | None
) -> set[tuple[int, int]]:
    resolved = resolved_class_subjects(teacher_id).subquery()
    stmt = select(resolved.c.class_id, resolved.c.subject_id)
    if academic_year_id is not None:
        slots = select(TimetableSlot.class_id, TimetableSlot.subject_id).where(
            TimetableSlot.teacher_id == teacher_id,
            TimetableSlot.academic_year_id == academic_year_id,
        )
        stmt = union(slots, stmt)
    return {(row[0], row[1]) for row in (await db.execute(stmt)).all()}


async def teaching_scope(
    db: AsyncSession, teacher_id: int, *, on: date | None = None
) -> TeachingScope:
    day = on or date.today()
    academic_year_id = await get_current_academic_year_id(db)
    replaced = await replaced_teachers(db, teacher_id, day)

    class_subjects: set[tuple[int, int]] = set()
    for tid in (teacher_id, *replaced):
        class_subjects |= await _own_class_subjects(db, tid, academic_year_id)
    return TeachingScope(
        teacher_id=teacher_id,
        class_subjects=frozenset(class_subjects),
        replaced_teacher_ids=replaced,
    )
