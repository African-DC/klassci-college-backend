"""Chargement des données du rapport DEEP — une passe, pas une requête par élève.

Le rapport parcourt les mêmes élèves une douzaine de fois, chapitre après
chapitre. Charger le contexte une bonne fois et le passer aux chapitres évite
le piège classique : quatre cents requêtes pour quatre cents élèves, sur un
document qu'un secrétariat imprime en fin de trimestre depuis une connexion
qui n'est pas toujours la meilleure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class, Level, Subject
from app.models.deep_report import ClassVisit, Scholarship, StudentTransfer, TeacherTraining
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.grade import Bulletin
from app.models.timetable import TimetableSlot
from app.models.user import Genre, StaffProfile, Student, TeacherProfile
from app.services.deep_report._metrics import Cycle, cycle_of_level

# Une inscription rejetée ou annulée n'occupe pas de place dans l'effectif ;
# une inscription en validation, si. C'est le périmètre déjà retenu par les
# statistiques DREN existantes, on ne le change pas en cours de route.
_COUNTED_STATUSES = (EnrollmentStatus.VALIDE, EnrollmentStatus.EN_VALIDATION)


def _enum_value(raw: object) -> str | None:
    """Valeur brute d'une colonne enum, que SQLAlchemy rende l'enum ou la chaîne."""
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


@dataclass
class StudentLine:
    """Un élève inscrit, avec tout ce que les tableaux réclament sur lui."""

    enrollment: Enrollment
    student: Student
    class_: Class
    level: Level
    cycle: Cycle
    bulletin: Bulletin | None
    is_repeater: bool | None  # None = historique indisponible, on ne devine pas

    @property
    def is_girl(self) -> bool | None:
        genre = _enum_value(self.student.genre)
        if genre == Genre.F.value:
            return True
        if genre == Genre.M.value:
            return False
        return None

    @property
    def average(self) -> Decimal | None:
        return self.bulletin.average if self.bulletin else None

    @property
    def rank(self) -> int | None:
        return self.bulletin.rank if self.bulletin else None

    @property
    def council_decision(self) -> str | None:
        return _enum_value(self.bulletin.council_decision) if self.bulletin else None

    @property
    def assignment_status(self) -> str | None:
        return _enum_value(self.enrollment.assignment_status)

    @property
    def birth_date(self) -> date | None:
        return self.student.birth_date

    @property
    def full_name(self) -> str:
        return f"{self.student.last_name} {self.student.first_name}".strip()


@dataclass
class DisciplineStaffing:
    """Service des enseignants, lu sur l'emploi du temps (tableaux 18 et 20)."""

    by_subject_cycle: dict[tuple[str, Cycle], set[int]] = field(default_factory=dict)
    classes_by_teacher: dict[int, set[str]] = field(default_factory=dict)
    subjects_by_teacher: dict[int, set[str]] = field(default_factory=dict)

    def add(
        self,
        subject_name: str,
        cycle: Cycle,
        teacher_id: int,
        class_name: str | None = None,
    ) -> None:
        self.by_subject_cycle.setdefault((subject_name, cycle), set()).add(teacher_id)
        self.subjects_by_teacher.setdefault(teacher_id, set()).add(subject_name)
        if class_name:
            self.classes_by_teacher.setdefault(teacher_id, set()).add(class_name)

    def count(self, subject_names: tuple[str, ...], cycle: Cycle) -> int:
        """Nombre d'enseignants distincts couvrant l'une des matières données."""
        teachers: set[int] = set()
        for name in subject_names:
            teachers |= self.by_subject_cycle.get((name, cycle), set())
        return len(teachers)

    @property
    def subject_names(self) -> set[str]:
        return {name for name, _cycle in self.by_subject_cycle}


@dataclass
class ReportContext:
    """Tout ce dont les chapitres ont besoin, chargé une seule fois."""

    academic_year: AcademicYear
    trimester: int
    lines: list[StudentLine]
    levels: list[Level]
    teachers: list[TeacherProfile]
    staff: list[StaffProfile]
    visits: list[ClassVisit]
    trainings: list[TeacherTraining]
    transfers: list[tuple[StudentTransfer, StudentLine]]
    scholarships: list[tuple[Scholarship, StudentLine]]
    staffing: DisciplineStaffing
    has_history: bool

    def lines_of_level(self, level_id: int) -> list[StudentLine]:
        return [line for line in self.lines if line.level.id == level_id]

    def classes_of_level(self, level_id: int) -> list[Class]:
        """Classes du niveau qui portent au moins une inscription comptée."""
        seen: dict[int, Class] = {}
        for line in self.lines:
            if line.level.id == level_id:
                seen.setdefault(line.class_.id, line.class_)
        return sorted(seen.values(), key=lambda cls: cls.name)

    @property
    def unassigned_count(self) -> int:
        """Inscriptions dont le statut d'affectation n'est pas renseigné."""
        return sum(1 for line in self.lines if line.assignment_status is None)

    @property
    def unknown_sex_count(self) -> int:
        """Élèves dont le sexe n'est pas renseigné — jamais rangés d'office."""
        return sum(1 for line in self.lines if line.is_girl is None)


async def load_context(db: AsyncSession, academic_year_id: int, trimester: int) -> ReportContext:
    """Charge le contexte complet du rapport en un nombre fixe de requêtes."""
    academic_year = await _load_academic_year(db, academic_year_id)
    enrollments = await _load_enrollments(db, academic_year_id)
    bulletins = await _load_bulletins(db, academic_year_id, trimester)
    repeated_levels, has_history = await _load_history(db, academic_year)

    lines: list[StudentLine] = []
    levels: dict[int, Level] = {}
    for enrollment in enrollments:
        class_ = enrollment.class_
        level = class_.level
        levels.setdefault(level.id, level)
        student = enrollment.student
        is_repeater: bool | None = None
        if has_history:
            is_repeater = (student.id, level.id) in repeated_levels
        lines.append(
            StudentLine(
                enrollment=enrollment,
                student=student,
                class_=class_,
                level=level,
                cycle=cycle_of_level(level.name, level.order),
                bulletin=bulletins.get(student.id),
                is_repeater=is_repeater,
            )
        )

    lines_by_enrollment = {line.enrollment.id: line for line in lines}

    return ReportContext(
        academic_year=academic_year,
        trimester=trimester,
        lines=lines,
        levels=sorted(levels.values(), key=lambda lvl: (lvl.order, lvl.name)),
        teachers=await _load_teachers(db),
        staff=await _load_staff(db),
        visits=await _load_visits(db, academic_year_id),
        trainings=await _load_trainings(db, academic_year_id),
        transfers=await _load_transfers(db, academic_year_id, lines_by_enrollment),
        scholarships=await _load_scholarships(db, academic_year_id, lines_by_enrollment),
        staffing=await _load_staffing(db, academic_year_id),
        has_history=has_history,
    )


async def _load_academic_year(db: AsyncSession, academic_year_id: int) -> AcademicYear:
    result = await db.execute(select(AcademicYear).where(AcademicYear.id == academic_year_id))
    academic_year = result.scalar_one_or_none()
    if academic_year is None:
        raise NotFoundError("AcademicYear", academic_year_id)
    return academic_year


async def _load_enrollments(db: AsyncSession, academic_year_id: int) -> list[Enrollment]:
    stmt = (
        select(Enrollment)
        .where(
            Enrollment.academic_year_id == academic_year_id,
            Enrollment.status.in_(_COUNTED_STATUSES),
        )
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.class_).selectinload(Class.level),
            selectinload(Enrollment.class_).selectinload(Class.series),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_bulletins(
    db: AsyncSession, academic_year_id: int, trimester: int
) -> dict[int, Bulletin]:
    stmt = select(Bulletin).where(
        Bulletin.academic_year_id == academic_year_id,
        Bulletin.trimester == trimester,
    )
    result = await db.execute(stmt)
    return {bulletin.student_id: bulletin for bulletin in result.scalars().all()}


async def _load_history(
    db: AsyncSession, academic_year: AcademicYear
) -> tuple[set[tuple[int, int]], bool]:
    """Couples (élève, niveau) déjà fréquentés lors d'une année antérieure.

    Sert la colonne « Qualité (Red / Non Red) ». Si l'établissement n'a aucune
    année antérieure en base, on ne peut rien affirmer : `has_history` vaut
    False et la colonne restera vide plutôt que d'annoncer « Non Red » pour
    tout le monde, ce qui serait faux dès le premier redoublant.
    """
    stmt = (
        select(Enrollment.student_id, Class.level_id)
        .join(Class, Class.id == Enrollment.class_id)
        .join(AcademicYear, AcademicYear.id == Enrollment.academic_year_id)
        .where(
            AcademicYear.start_date < academic_year.start_date,
            Enrollment.status.in_(_COUNTED_STATUSES),
        )
    )
    result = await db.execute(stmt)
    rows = result.all()
    return {(row[0], row[1]) for row in rows}, bool(rows)


async def _load_teachers(db: AsyncSession) -> list[TeacherProfile]:
    stmt = select(TeacherProfile).order_by(TeacherProfile.last_name, TeacherProfile.first_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_staff(db: AsyncSession) -> list[StaffProfile]:
    stmt = select(StaffProfile).order_by(StaffProfile.last_name, StaffProfile.first_name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_visits(db: AsyncSession, academic_year_id: int) -> list[ClassVisit]:
    stmt = (
        select(ClassVisit)
        .where(ClassVisit.academic_year_id == academic_year_id)
        .options(
            selectinload(ClassVisit.teacher),
            selectinload(ClassVisit.subject),
            selectinload(ClassVisit.class_),
        )
        .order_by(ClassVisit.visit_date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_trainings(db: AsyncSession, academic_year_id: int) -> list[TeacherTraining]:
    stmt = (
        select(TeacherTraining)
        .where(TeacherTraining.academic_year_id == academic_year_id)
        .options(
            selectinload(TeacherTraining.teacher),
            selectinload(TeacherTraining.subject),
        )
        .order_by(TeacherTraining.training_date)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _load_transfers(
    db: AsyncSession, academic_year_id: int, lines: dict[int, StudentLine]
) -> list[tuple[StudentTransfer, StudentLine]]:
    stmt = (
        select(StudentTransfer)
        .join(Enrollment, Enrollment.id == StudentTransfer.enrollment_id)
        .where(Enrollment.academic_year_id == academic_year_id)
        .order_by(StudentTransfer.transfer_date)
    )
    result = await db.execute(stmt)
    pairs: list[tuple[StudentTransfer, StudentLine]] = []
    for transfer in result.scalars().all():
        line = lines.get(transfer.enrollment_id)
        # Une inscription annulée ou archivée sort du périmètre du rapport :
        # son transfert n'a plus de ligne à nourrir.
        if line is not None:
            pairs.append((transfer, line))
    return pairs


async def _load_scholarships(
    db: AsyncSession, academic_year_id: int, lines: dict[int, StudentLine]
) -> list[tuple[Scholarship, StudentLine]]:
    stmt = (
        select(Scholarship)
        .join(Enrollment, Enrollment.id == Scholarship.enrollment_id)
        .where(Enrollment.academic_year_id == academic_year_id)
        .order_by(Scholarship.granted_on)
    )
    result = await db.execute(stmt)
    pairs: list[tuple[Scholarship, StudentLine]] = []
    for scholarship in result.scalars().all():
        line = lines.get(scholarship.enrollment_id)
        if line is not None:
            pairs.append((scholarship, line))
    return pairs


async def _load_staffing(db: AsyncSession, academic_year_id: int) -> DisciplineStaffing:
    """Enseignants distincts par matière et par cycle, lus sur l'emploi du temps.

    Le rattachement enseignant ↔ classe est implicite dans KLASSCI : il passe
    par les créneaux, pas par une table de service. C'est donc l'emploi du
    temps qui dit qui enseigne quoi, et à quel cycle.
    """
    stmt = (
        select(TimetableSlot.teacher_id, Subject.name, Class.name, Level.name, Level.order)
        .join(Subject, Subject.id == TimetableSlot.subject_id)
        .join(Class, Class.id == TimetableSlot.class_id)
        .join(Level, Level.id == Class.level_id)
        .where(TimetableSlot.academic_year_id == academic_year_id)
        .distinct()
    )
    result = await db.execute(stmt)
    staffing = DisciplineStaffing()
    for teacher_id, subject_name, class_name, level_name, level_order in result.all():
        staffing.add(
            subject_name,
            cycle_of_level(level_name, level_order),
            teacher_id,
            class_name,
        )
    return staffing
