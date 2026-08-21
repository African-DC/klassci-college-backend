"""Les deux registres de la vie scolaire : celui des élèves, celui des profs.

L'appel est ce qu'une école tient tous les jours et ce qu'un parent réclame en
premier. Un registre vide vide du même coup le taux d'assiduité du bulletin,
la liste des élèves à surveiller et l'écran de suivi de l'éducateur.

On ne relève pas tous les jours de l'année : six journées par trimestre et par
classe suffisent à faire vivre les moyennes et les alertes, là où deux cents
appels quotidiens ne feraient qu'alourdir la base sans rien montrer de plus.

Quelques élèves portent volontairement un dossier plus lourd. Une école n'a
pas une absence uniformément répartie sur six cents inscrits : elle a une
poignée de cas suivis, et c'est eux que le conseil de discipline convoque.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import date, time

from sqlalchemy import func, select

from app.cli.seed_demo.context import SeedContext, logger
from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.attendance import AttendanceContext, AttendanceEntityType, TeacherSessionAttendance
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.timetable import TimetableSlot
from app.models.user import TeacherProfile
from app.schemas.attendance import AttendanceRecordInput, SessionCreate
from app.schemas.teacher_attendance import TeacherAttendanceCreate, TeacherSelfDeclareCreate
from app.services import attendance_service, teacher_attendance_service

#: Journées relevées par classe et par trimestre, soit dix-huit sur l'année.
DAYS_PER_TRIMESTER = 6

#: Jours de classe échantillonnés par trimestre pour dater les créneaux des
#: enseignants. Plus large que le registre élève : il faut de quoi tirer une
#: trentaine de séances par professeur sans repasser deux fois au même endroit.
DATES_PER_TRIMESTER = 12

#: Un élève sur dix-sept traîne un dossier d'assiduité. Le critère est le
#: reste de son identifiant : deux exécutions désignent les mêmes.
FRAGILE_MODULUS = 17

#: Répartition ordinaire, puis celle des élèves suivis.
ORDINARY_MIX: tuple[tuple[str, int], ...] = (
    ("present", 88),
    ("absent", 6),
    ("late", 4),
    ("excused", 2),
)
FRAGILE_MIX: tuple[tuple[str, int], ...] = (
    ("present", 62),
    ("absent", 22),
    ("late", 12),
    ("excused", 4),
)

PUPIL_NOTES: dict[str, tuple[str, ...]] = {
    "absent": (
        "Absence non justifiée à ce jour.",
        "Absence signalée par la famille, sans pièce fournie.",
    ),
    "late": (
        "Retard, arrivée après l'appel.",
        "Retard, circulation dense sur l'axe d'Angré.",
    ),
    "excused": (
        "Absence justifiée par un certificat médical.",
        "Absence autorisée par la vie scolaire.",
    ),
}

#: Répartition du pointage enseignant. Un professeur assure la quasi-totalité
#: de ses heures : ce sont les rares manquantes que l'administration suit.
TEACHER_MIX: tuple[tuple[str, int], ...] = (
    ("present", 90),
    ("late", 4),
    ("absent_excused", 4),
    ("absent_unexcused", 2),
)

TEACHER_NOTES: dict[str, tuple[str, ...]] = {
    "late": (
        "Retard signalé par le surveillant de couloir.",
        "Retard, cours précédent dans un autre établissement.",
    ),
    "absent_excused": (
        "Convocation à la DRENA, absence couverte.",
        "Congé maladie, certificat déposé au secrétariat.",
    ),
    "absent_unexcused": (
        "Cours non assuré, aucune justification reçue.",
        "Absence non justifiée, remplacement improvisé.",
    ),
}

#: Volume du pointage enseignant : une borne haute pour que l'étape reste
#: rapide, et un plancher pour que chaque fiche professeur ait de quoi parler.
TEACHER_RECORDS_CAP = 800
MIN_SESSIONS_PER_TEACHER = 25
MAX_SESSIONS_PER_TEACHER = 40

#: Auto-déclarations laissées en attente, pour que l'écran « à valider » de
#: l'administration ait quelque chose à montrer.
SELF_DECLARED_COUNT = 10

#: Correspondance entre le jour d'un créneau et le jour d'une date réelle.
WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
)


def _draw_with(rng: random.Random, mix: Sequence[tuple[str, int]]) -> str:
    """Tire un statut selon des poids entiers, sur un générateur donné."""
    running = 0
    draw = rng.randint(1, sum(weight for _status, weight in mix))
    for status, weight in mix:
        running += weight
        if draw <= running:
            return status
    return mix[-1][0]


def _draw(ctx: SeedContext, mix: Sequence[tuple[str, int]]) -> str:
    """Tire un statut sur le générateur de l'étape."""
    return _draw_with(ctx.rng, mix)


def _session_rng(teacher_id: int, slot_id: int | None, when: date) -> random.Random:
    """Un générateur propre à une séance, indépendant de l'ordre d'exécution.

    Le pointage saute les séances déjà enregistrées. Puiser dans un flux
    commun ferait donc avancer le tirage différemment à chaque relance, et le
    semis choisirait d'autres séances : huit cents pointages de plus par
    exécution. Une graine dérivée de la séance elle-même supprime la question.
    """
    return random.Random(f"{teacher_id}/{slot_id}/{when.isoformat()}")


def _arrival(ctx: SeedContext) -> time:
    """L'heure d'arrivée d'un retardataire, entre 7 h 15 et 8 h 30."""
    minutes = 7 * 60 + 15 + ctx.rng.randint(0, 75)
    return time(minutes // 60, minutes % 60)


def _pupil_record(ctx: SeedContext, student_id: int) -> AttendanceRecordInput:
    """Le sort d'un élève ce jour-là, motif compris quand il n'est pas là."""
    mix = FRAGILE_MIX if student_id % FRAGILE_MODULUS == 0 else ORDINARY_MIX
    status = _draw(ctx, mix)
    if status == "present":
        return AttendanceRecordInput(student_id=student_id, status=status)
    return AttendanceRecordInput(
        student_id=student_id,
        status=status,
        time_in=_arrival(ctx) if status == "late" else None,
        notes=ctx.rng.choice(PUPIL_NOTES[status]),
    )


async def _pupils_by_class(ctx: SeedContext) -> dict[int, list[int]]:
    """Les inscrits validés de chaque classe.

    Un dossier en cours d'instruction n'est pas encore un élève : l'appeler
    fausserait l'effectif de la classe autant que son taux d'assiduité.
    """
    stmt = select(Enrollment.class_id, Enrollment.student_id).where(
        Enrollment.academic_year_id == ctx.academic_year_id,
        Enrollment.status == EnrollmentStatus.VALIDE.value,
    )
    grouped: dict[int, list[int]] = {}
    for class_id, student_id in (await ctx.db.execute(stmt)).all():
        grouped.setdefault(int(class_id), []).append(int(student_id))
    for roster in grouped.values():
        roster.sort()
    return grouped


async def _existing_sessions(ctx: SeedContext) -> set[tuple[int, date]]:
    """Les appels déjà tenus, repérés par leur classe et leur date."""
    stmt = select(AttendanceContext.context_id, AttendanceContext.date).where(
        AttendanceContext.academic_year_id == ctx.academic_year_id,
        AttendanceContext.entity_type == AttendanceEntityType.CLASS.value,
    )
    return {(int(context_id), day) for context_id, day in (await ctx.db.execute(stmt)).all()}


async def mark_pupil_registers(ctx: SeedContext) -> None:
    """Tient l'appel de chaque classe, six journées par trimestre."""
    rosters = await _pupils_by_class(ctx)
    done = await _existing_sessions(ctx)

    for class_id, roster in sorted(rosters.items()):
        if not roster:
            continue
        for trimester, _start, _end in ctx.trimesters:
            for day in ctx.school_days(trimester, DAYS_PER_TRIMESTER):
                if (class_id, day) in done:
                    continue
                records = [_pupil_record(ctx, student_id) for student_id in roster]
                await attendance_service.create_session(
                    ctx.db,
                    SessionCreate(
                        entity_type="class",
                        context_id=class_id,
                        date=day,
                        academic_year_id=ctx.academic_year_id,
                        records=records,
                    ),
                    created_by=ctx.actor_id,
                )
                done.add((class_id, day))
                ctx.tally("appels")
                ctx.tally("présences relevées", len(records))


async def _dated_sessions(ctx: SeedContext) -> dict[int, list[tuple[int, date]]]:
    """Les créneaux de chaque enseignant, projetés sur des dates réelles.

    Un créneau d'emploi du temps est une récurrence, pas une séance. Le
    pointage, lui, porte sur une séance datée : on croise donc la grille avec
    les jours de classe échantillonnés dans les trois trimestres.
    """
    calendar: list[date] = []
    for trimester, _start, _end in ctx.trimesters:
        calendar.extend(ctx.school_days(trimester, DATES_PER_TRIMESTER))

    stmt = select(TimetableSlot.id, TimetableSlot.teacher_id, TimetableSlot.day).where(
        TimetableSlot.academic_year_id == ctx.academic_year_id
    )
    agenda: dict[int, list[tuple[int, date]]] = {}
    for slot_id, teacher_id, day in (await ctx.db.execute(stmt)).all():
        for when in calendar:
            if when.weekday() < len(WEEKDAY_NAMES) and WEEKDAY_NAMES[when.weekday()] == day:
                agenda.setdefault(int(teacher_id), []).append((int(slot_id), when))
    for sessions in agenda.values():
        sessions.sort()
    return agenda


async def _pending_declarations(ctx: SeedContext) -> int:
    """Auto-déclarations déjà en attente de validation."""
    stmt = (
        select(func.count())
        .select_from(TeacherSessionAttendance)
        .where(TeacherSessionAttendance.is_validated.is_(False))
    )
    return int((await ctx.db.execute(stmt)).scalar_one() or 0)


async def _existing_teacher_records(ctx: SeedContext) -> set[tuple[int, int, date]]:
    """Les pointages déjà saisis, par enseignant, créneau et date."""
    stmt = select(
        TeacherSessionAttendance.teacher_id,
        TeacherSessionAttendance.slot_id,
        TeacherSessionAttendance.date,
    )
    return {
        (int(teacher_id), int(slot_id), day)
        for teacher_id, slot_id, day in (await ctx.db.execute(stmt)).all()
        if slot_id is not None
    }


async def _teacher_users(ctx: SeedContext) -> dict[int, int]:
    """Le compte utilisateur de chaque enseignant, requis pour s'auto-déclarer."""
    rows = (await ctx.db.execute(select(TeacherProfile.id, TeacherProfile.user_id))).all()
    return {int(teacher_id): int(user_id) for teacher_id, user_id in rows}


async def mark_teacher_registers(ctx: SeedContext) -> None:
    """Pointe les séances des enseignants, dont quelques-unes en attente.

    L'administration saisit l'essentiel et valide donc d'office. Une poignée
    de séances passe par l'auto-déclaration du professeur : elles restent en
    attente, ce qui donne son contenu à la file de validation.
    """
    agenda = await _dated_sessions(ctx)
    if not agenda:
        logger.info("Aucun créneau daté : le pointage enseignant est sans objet.")
        return

    done = await _existing_teacher_records(ctx)
    users = await _teacher_users(ctx)
    quota = min(
        MAX_SESSIONS_PER_TEACHER,
        max(MIN_SESSIONS_PER_TEACHER, TEACHER_RECORDS_CAP // len(agenda)),
    )
    # Le plafond porte sur le total, pas sur ce que cette exécution ajoute :
    # une borne comptée à neuf laisserait le registre grossir de huit cents
    # lignes à chaque relance.
    written = len(done)
    pending_left = max(0, SELF_DECLARED_COUNT - await _pending_declarations(ctx))

    for teacher_id, sessions in sorted(agenda.items()):
        if written >= TEACHER_RECORDS_CAP:
            break
        picked = random.Random(teacher_id).sample(sessions, min(quota, len(sessions)))
        declared_here = False

        for slot_id, when in sorted(picked, key=lambda entry: (entry[1], entry[0])):
            if (teacher_id, slot_id, when) in done:
                continue
            seance = _session_rng(teacher_id, slot_id, when)
            status = _draw_with(seance, TEACHER_MIX)
            late = seance.randint(5, 25) if status == "late" else 0
            note = None if status == "present" else seance.choice(TEACHER_NOTES[status])
            self_declared = not declared_here and pending_left > 0 and teacher_id in users

            fields = {
                "slot_id": slot_id,
                "date": when,
                "status": status,
                "late_minutes": late,
                "notes": note,
            }
            try:
                if self_declared:
                    await teacher_attendance_service.self_declare(
                        ctx.db, users[teacher_id], TeacherSelfDeclareCreate(**fields)
                    )
                    pending_left -= 1
                else:
                    await teacher_attendance_service.record_attendance(
                        ctx.db,
                        teacher_id,
                        TeacherAttendanceCreate(**fields),
                        declared_by_user_id=ctx.actor_id,
                    )
            except (BusinessValidationError, NotFoundError) as error:
                logger.warning(
                    "Pointage non enregistré (enseignant %s, %s) : %s",
                    teacher_id,
                    when,
                    error.detail,
                )
                continue

            declared_here = declared_here or self_declared
            done.add((teacher_id, slot_id, when))
            written += 1
            ctx.tally("pointages enseignants")
            if written >= TEACHER_RECORDS_CAP:
                break


async def run(ctx: SeedContext) -> None:
    await mark_pupil_registers(ctx)
    await mark_teacher_registers(ctx)
