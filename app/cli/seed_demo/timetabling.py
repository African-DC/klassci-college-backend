"""L'emploi du temps hebdomadaire de chaque division.

Une grille vide est le trou le plus visible d'une démonstration : c'est le
premier écran qu'un directeur ouvre, et il n'y a rien à raconter devant une
semaine blanche. On pose donc une semaine complète pour toutes les classes.

Le rythme est celui d'un établissement ivoirien : cours le matin de 7 h à
midi, longue coupure méridienne, reprise de 15 h à 17 h, et samedi matin
seulement. Les élèves ne bougent pas de leur salle, ce sont les enseignants
qui se déplacent : chaque créneau se tient donc dans la salle homonyme de la
classe.

L'ordonnancement est écrit ici, en Python, et non délégué au générateur
OR-Tools : celui-ci passe par une tâche Celery, qui suppose un ouvrier vivant
que le semis n'a aucune raison d'exiger.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.cli.seed_demo import plan
from app.cli.seed_demo.context import SeedContext, logger
from app.core.exceptions import BusinessValidationError, ConflictError
from app.models.academic import Class, SchoolSettings, Subject
from app.models.timetable import DayOfWeek, TimetableSlot
from app.schemas.timetable import TimetableSlotCreate
from app.services import timetable_service

#: Bornes de la journée ivoirienne. La coupure de midi est réelle : sans elle,
#: la grille afficherait des cours à 13 h que personne n'a jamais assurés.
MORNING_END_HOUR = 12
AFTERNOON_START_HOUR = 15

#: Valeurs de repli quand l'établissement n'a pas encore réglé sa grille.
DEFAULT_SLOT_MINUTES = 60
DEFAULT_DAY_START_HOUR = 7
DEFAULT_DAY_END_HOUR = 17

#: Les cinq jours pleins ; le samedi n'a que sa matinée.
FULL_DAYS: tuple[DayOfWeek, ...] = (
    DayOfWeek.MONDAY,
    DayOfWeek.TUESDAY,
    DayOfWeek.WEDNESDAY,
    DayOfWeek.THURSDAY,
    DayOfWeek.FRIDAY,
)

#: Deux heures de la même matière le même jour, jamais trois : au-delà, la
#: grille cesse de ressembler à un emploi du temps et devient un stage.
MAX_HOURS_SAME_DAY = 2

#: (matière, clé enseignant, heures hebdomadaires)
SubjectDemand = tuple[str, str, int]
#: (jour, début « HH:MM », fin « HH:MM »)
GridSlot = tuple[str, str, str]
#: (matière, clé enseignant, jour, début, fin)
Placement = tuple[str, str, str, str, str]


def teacher_key(teacher_id: int) -> str:
    """Clé d'occupation d'un enseignant, distincte de celle d'une classe."""
    return f"t{teacher_id}"


def class_key(class_id: int) -> str:
    """Clé d'occupation d'une classe, distincte de celle d'un enseignant."""
    return f"c{class_id}"


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _window(start_hour: int, end_hour: int, duration: int) -> list[tuple[str, str]]:
    """Découpe une plage de la journée en heures pleines de `duration`."""
    slots: list[tuple[str, str]] = []
    cursor, limit = start_hour * 60, end_hour * 60
    while cursor + duration <= limit:
        slots.append((_hhmm(cursor), _hhmm(cursor + duration)))
        cursor += duration
    return slots


def build_grid(*, duration_minutes: int, day_start_hour: int, day_end_hour: int) -> list[GridSlot]:
    """La semaine ouvrable de l'établissement, créneau par créneau."""
    morning = _window(min(day_start_hour, MORNING_END_HOUR), MORNING_END_HOUR, duration_minutes)
    afternoon = _window(
        AFTERNOON_START_HOUR, max(day_end_hour, AFTERNOON_START_HOUR), duration_minutes
    )
    grid: list[GridSlot] = []
    for day in FULL_DAYS:
        grid.extend((day.value, start, end) for start, end in (*morning, *afternoon))
    grid.extend((DayOfWeek.SATURDAY.value, start, end) for start, end in morning)
    return grid


def _adjacency(spans: set[tuple[str, str]] | None, start: str, end: str) -> int:
    """0 si le créneau prolonge une heure déjà posée ce jour-là, 1 sinon.

    Deux heures d'affilée valent mieux que deux heures séparées par trois
    autres matières : c'est ainsi qu'une école place un devoir surveillé.
    """
    if not spans:
        return 0
    return 0 if any(begin == end or finish == start for begin, finish in spans) else 1


def build_week(
    subjects: Sequence[SubjectDemand],
    grid: Sequence[GridSlot],
    busy: frozenset[tuple[str, str, str]] | set[tuple[str, str, str]],
    *,
    occupant: str,
) -> list[Placement]:
    """Place le programme d'une classe dans la grille, sans chevauchement.

    `busy` contient les positions `(clé d'occupation, jour, début)` déjà
    prises, toutes classes et tous enseignants confondus ; il est **lu et non
    modifié**, à charge de l'appelant d'y reporter le résultat. `occupant` est
    la clé de la classe qu'on garnit.

    Invariants garantis sur la liste rendue :

    - aucun enseignant n'apparaît deux fois au même `(jour, début)`, ni dans le
      résultat, ni en collision avec `busy` ;
    - la classe n'apparaît pas deux fois au même `(jour, début)`, ni en
      collision avec `busy` ;
    - une même matière n'occupe jamais plus de `MAX_HOURS_SAME_DAY` heures dans
      la journée, et sa seconde heure est contiguë à la première quand la
      grille le permet ;
    - le nombre d'heures rendues vaut la somme des heures demandées dès que la
      grille est assez large ; sinon il est inférieur, et l'appelant compare
      pour signaler ce qui n'a pas tenu.
    """
    taken = set(busy)
    placed: list[Placement] = []
    per_day: dict[tuple[str, str], int] = {}
    class_load: dict[str, int] = {}
    spans: dict[tuple[str, str], set[tuple[str, str]]] = {}

    # Les matières lourdes d'abord : ce sont elles qui ont le moins de
    # positions acceptables, et les caser en dernier revient à les émietter.
    for subject, teacher, hours in sorted(subjects, key=lambda item: (-item[2], item[0])):
        for _hour in range(hours):
            best: tuple[tuple[int, int, int, int], str, str, str] | None = None
            for index, (day, start, end) in enumerate(grid):
                if (occupant, day, start) in taken or (teacher, day, start) in taken:
                    continue
                same_day = per_day.get((subject, day), 0)
                if same_day >= MAX_HOURS_SAME_DAY:
                    continue
                score = (
                    same_day,
                    _adjacency(spans.get((subject, day)), start, end),
                    class_load.get(day, 0),
                    index,
                )
                if best is None or score < best[0]:
                    best = (score, day, start, end)
            if best is None:
                break

            _score, day, start, end = best
            placed.append((subject, teacher, day, start, end))
            taken.add((occupant, day, start))
            taken.add((teacher, day, start))
            per_day[(subject, day)] = per_day.get((subject, day), 0) + 1
            class_load[day] = class_load.get(day, 0) + 1
            spans.setdefault((subject, day), set()).add((start, end))

    return placed


async def _grid_settings(ctx: SeedContext) -> tuple[int, int, int]:
    """La grille réglée par l'établissement, ou celle d'un collège ordinaire."""
    row = (await ctx.db.execute(select(SchoolSettings).limit(1))).scalar_one_or_none()
    if row is None:
        return DEFAULT_SLOT_MINUTES, DEFAULT_DAY_START_HOUR, DEFAULT_DAY_END_HOUR
    return (
        row.slot_duration_minutes or DEFAULT_SLOT_MINUTES,
        row.day_start_hour or DEFAULT_DAY_START_HOUR,
        row.day_end_hour or DEFAULT_DAY_END_HOUR,
    )


async def _existing_slots(ctx: SeedContext) -> tuple[set[tuple[str, str, str]], set[int]]:
    """Ce qui est déjà posé : occupations à respecter, classes à ne pas toucher.

    Une classe dont l'emploi du temps existe est laissée entière. Compléter une
    grille à moitié faite reviendrait à mêler l'ordonnancement du semis à celui
    d'un responsable qui, lui, sait pourquoi il a placé ses heures ainsi.
    """
    rows = (
        (
            await ctx.db.execute(
                select(TimetableSlot).where(TimetableSlot.academic_year_id == ctx.academic_year_id)
            )
        )
        .scalars()
        .all()
    )

    busy: set[tuple[str, str, str]] = set()
    served: set[int] = set()
    for row in rows:
        start = row.start_time.strftime("%H:%M")
        busy.add((class_key(row.class_id), row.day, start))
        busy.add((teacher_key(row.teacher_id), row.day, start))
        served.add(row.class_id)
    return busy, served


async def _room_names(ctx: SeedContext) -> dict[int, str | None]:
    """La salle attitrée de chaque classe, telle que le service la résout."""
    rows = (await ctx.db.execute(select(Class).options(selectinload(Class.room)))).scalars().all()
    return {row.id: (row.room.name if row.room else None) for row in rows}


async def _subject_teachers(ctx: SeedContext) -> dict[int, int | None]:
    """Le titulaire déclaré sur chaque instance de matière."""
    rows = (await ctx.db.execute(select(Subject.id, Subject.teacher_id))).all()
    return {int(subject_id): teacher_id for subject_id, teacher_id in rows}


def _demands(
    ctx: SeedContext,
    level: str,
    serie: str | None,
    titulars: dict[int, int | None],
) -> tuple[list[SubjectDemand], dict[str, tuple[int, int]]]:
    """Le programme d'une classe, traduit en heures à caser et en identifiants."""
    demands: list[SubjectDemand] = []
    lookup: dict[str, tuple[int, int]] = {}

    for name, _coefficient, hours in plan.curriculum_for(level, serie):
        subject_id = ctx.subject_ids.get((level, serie, name))
        if subject_id is None:
            continue
        pool = ctx.teachers_by_subject.get(name) or []
        teacher_id = titulars.get(subject_id) or (pool[0] if pool else None)
        if teacher_id is None:
            logger.warning("Aucun enseignant pour « %s » en %s : matière non placée.", name, level)
            continue
        demands.append((name, teacher_key(teacher_id), hours))
        lookup[name] = (subject_id, teacher_id)

    return demands, lookup


async def fill_timetables(ctx: SeedContext) -> None:
    """Garnit la semaine de chaque division encore sans emploi du temps."""
    duration, day_start, day_end = await _grid_settings(ctx)
    grid = build_grid(duration_minutes=duration, day_start_hour=day_start, day_end_hour=day_end)
    busy, served = await _existing_slots(ctx)
    rooms = await _room_names(ctx)
    titulars = await _subject_teachers(ctx)

    for level, serie, division in plan.class_plan():
        class_id = ctx.class_ids.get((level, serie, division))
        label = plan.class_display_name(level, division)
        if class_id is None or class_id in served:
            continue

        demands, lookup = _demands(ctx, level, serie, titulars)
        placements = build_week(demands, grid, busy, occupant=class_key(class_id))
        requested = sum(hours for _name, _teacher, hours in demands)
        if len(placements) < requested:
            logger.warning(
                "%s : %s heures placées sur %s, la semaine ouvrable est trop courte.",
                label,
                len(placements),
                requested,
            )

        room = rooms.get(class_id)
        for name, teacher, day, start, end in placements:
            subject_id, teacher_id = lookup[name]
            try:
                await timetable_service.create_slot(
                    ctx.db,
                    TimetableSlotCreate(
                        class_id=class_id,
                        teacher_id=teacher_id,
                        subject_id=subject_id,
                        academic_year_id=ctx.academic_year_id,
                        day=DayOfWeek(day),
                        start_time=start,
                        end_time=end,
                        room=room,
                    ),
                    created_by=ctx.actor_id,
                )
            except (BusinessValidationError, ConflictError) as error:
                logger.warning("%s : créneau %s %s non posé (%s).", label, day, start, error.detail)
                continue

            busy.add((class_key(class_id), day, start))
            busy.add((teacher, day, start))
            ctx.tally("créneaux")


async def run(ctx: SeedContext) -> None:
    await fill_timetables(ctx)
