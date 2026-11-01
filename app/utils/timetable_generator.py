"""Generateur d'emploi du temps — solveur OR-Tools CP-SAT.

Granularite configurable (ex: 30min, 45min, 60min).
Le solveur travaille en blocs de `slot_duration_minutes` et retourne
des time ranges (start_time, end_time) apres fusion des blocs consecutifs.

Contraintes dures :
- Un enseignant ne peut avoir qu'un seul cours par bloc
- Une classe ne peut avoir qu'un seul cours par bloc
- Chaque assignation obtient le nombre exact de minutes, sans cours trop court
- Les indisponibilites enseignant sont respectees
- Pas de cours a cheval sur 2 jours (consecutivite intra-journee)

Contraintes souples :
- Preferer les creneaux marques "preferred" par les enseignants
"""

from dataclasses import dataclass, field, replace
from datetime import time

from ortools.sat.python import cp_model

MAX_SOLVER_SECONDS = 30.0
PREFERRED_BONUS = 10
MIN_LESSON_MINUTES = 30

XVars = dict[tuple[int, int], cp_model.IntVar]


@dataclass
class Assignment:
    """Assignation prof-matiere pour une classe."""

    teacher_id: int
    subject_id: int
    minutes_per_week: int
    partial: bool = False  # single shorter lesson, placed inside one block


@dataclass
class SlotBlock:
    """Un bloc de temps dans la grille du solveur."""

    day: str
    start_minutes: int  # minutes from midnight (e.g., 480 = 08:00)
    end_minutes: int
    day_index: int  # 0=Monday, 1=Tuesday, etc.
    index: int  # global index in the flat list


@dataclass
class MergedSlot:
    """Resultat fusionne : un creneau continu pour la DB."""

    assignment_idx: int
    day: str
    start_time: time
    end_time: time


@dataclass
class GeneratorResult:
    """Resultat du solveur."""

    feasible: bool
    merged_slots: list[MergedSlot] = field(default_factory=list)
    timed_out: bool = False  # no answer within the time limit, not a proof of impossibility


def plan_assignments(
    required: list[Assignment], slot_duration_minutes: int
) -> tuple[list[Assignment], list[tuple[int, int]]]:
    """Split each weekly volume into whole lessons plus at most one shorter lesson.

    The grid keeps its configured duration, whatever a manual lesson leaves over.
    A remainder too short to be a lesson is returned as (subject_id, minutes)
    so that the caller reports it instead of scheduling it. A shorter lesson
    reserves its whole block: the minutes after it stay free, unscheduled.
    """
    planned: list[Assignment] = []
    unplanned: list[tuple[int, int]] = []
    shortest = min(MIN_LESSON_MINUTES, slot_duration_minutes)
    for asg in required:
        total = asg.minutes_per_week
        remainder = total % slot_duration_minutes
        if total > remainder:
            planned.append(replace(asg, minutes_per_week=total - remainder))
        if remainder >= shortest:
            planned.append(replace(asg, minutes_per_week=remainder, partial=True))
        elif remainder:
            unplanned.append((asg.subject_id, remainder))
    return planned, unplanned


def build_blocks(
    days: list[str],
    day_start_hour: int,
    day_end_hour: int,
    slot_duration_minutes: int,
    blocked_periods: dict[str, list[tuple[int, int]]] | None = None,
) -> list[SlotBlock]:
    """Build minute-precise teaching segments, restarting after every interruption.

    Each continuous stretch starts at the configured day start or directly at
    the end of a break/manual lesson. Thus 10:15–11:15 is a genuine 60-minute
    lesson, not a lost 10:00–11:00 block. Trailing fragments are retained and
    penalized by the solver, unless they are too short to be a lesson.
    """
    if slot_duration_minutes <= 0 or day_start_hour >= day_end_hour:
        raise ValueError("Invalid timetable grid settings")
    if not 0 <= day_start_hour < day_end_hour <= 24:
        raise ValueError("Working hours must fit within one day")
    blocks: list[SlotBlock] = []
    for day_idx, day in enumerate(days):
        lower, upper = day_start_hour * 60, day_end_hour * 60
        ranges = sorted(
            (max(lower, int(a)), min(upper, int(b)))
            for a, b in (blocked_periods or {}).get(day, [])
            if int(a) < int(b) and int(b) > lower and int(a) < upper
        )
        merged: list[tuple[int, int]] = []
        for a, b in ranges:
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        cursor = lower
        for stop_start, stop_end in [*merged, (upper, upper)]:
            while cursor < stop_start:
                finish = min(cursor + slot_duration_minutes, stop_start)
                if finish - cursor >= min(MIN_LESSON_MINUTES, slot_duration_minutes):
                    blocks.append(SlotBlock(day, cursor, finish, day_idx, len(blocks)))
                cursor = finish
            cursor = max(cursor, stop_end)
    return blocks


def minutes_to_time(minutes: int) -> time:
    """Convertit des minutes depuis minuit en datetime.time."""
    return time(minutes // 60, minutes % 60)


def merge_consecutive_blocks(
    assigned_block_indices: list[int],
    blocks: list[SlotBlock],
    assignment_idx: int,
) -> list[MergedSlot]:
    """Fusionne les blocs consecutifs du meme jour en creneaux continus."""
    if not assigned_block_indices:
        return []

    sorted_indices = sorted(assigned_block_indices)
    result: list[MergedSlot] = []

    # Start first group
    current_day = blocks[sorted_indices[0]].day
    current_start = blocks[sorted_indices[0]].start_minutes
    current_end = blocks[sorted_indices[0]].end_minutes

    for i in range(1, len(sorted_indices)):
        blk = blocks[sorted_indices[i]]
        # Check if consecutive (same day + start == previous end)
        if blk.day == current_day and blk.start_minutes == current_end:
            current_end = blk.end_minutes
        else:
            # Save current group and start new one
            result.append(
                MergedSlot(
                    assignment_idx=assignment_idx,
                    day=current_day,
                    start_time=minutes_to_time(current_start),
                    end_time=minutes_to_time(current_end),
                )
            )
            current_day = blk.day
            current_start = blk.start_minutes
            current_end = blk.end_minutes

    # Save last group
    result.append(
        MergedSlot(
            assignment_idx=assignment_idx,
            day=current_day,
            start_time=minutes_to_time(current_start),
            end_time=minutes_to_time(current_end),
        )
    )

    return result


def join_adjacent_lessons(
    slots: list[MergedSlot], assignments: list[Assignment]
) -> list[MergedSlot]:
    """Show a whole lesson followed by its shorter part as one continuous course."""
    joined: list[MergedSlot] = []
    for slot in sorted(slots, key=lambda s: (s.day, s.start_time)):
        previous = joined[-1] if joined else None
        if (
            previous is not None
            and previous.day == slot.day
            and previous.end_time == slot.start_time
            and assignments[previous.assignment_idx].teacher_id
            == assignments[slot.assignment_idx].teacher_id
            and assignments[previous.assignment_idx].subject_id
            == assignments[slot.assignment_idx].subject_id
        ):
            previous.end_time = slot.end_time
        else:
            joined.append(slot)
    return joined


def solve(
    assignments: list[Assignment],
    blocks: list[SlotBlock],
    slot_duration_minutes: int,
    teacher_unavailabilities: dict[int, set[int]] | None = None,
    preferred_blocks: dict[int, set[int]] | None = None,
) -> GeneratorResult:
    """Lance le solveur CP-SAT avec granularite configurable.

    Args:
        assignments: liste d'assignations prof-matiere avec leurs minutes hebdomadaires
        blocks: grille de blocs (construite par build_blocks)
        slot_duration_minutes: duree d'un bloc en minutes
        teacher_unavailabilities: teacher_id -> set d'indices bloques
        preferred_blocks: teacher_id -> set d'indices preferes

    Returns:
        GeneratorResult avec merged_slots (creneaux fusionnes prets pour la DB).
    """
    if not assignments or not blocks:
        return GeneratorResult(feasible=not any(a.minutes_per_week > 0 for a in assignments))
    if any(a.minutes_per_week < 0 for a in assignments):
        return GeneratorResult(feasible=False)

    model = cp_model.CpModel()
    n_a, n_b = len(assignments), len(blocks)

    # Variables booleennes x[a, b] = 1 si l'assignation a est placee au bloc b
    x: XVars = {(a, b): model.new_bool_var(f"x_{a}_{b}") for a in range(n_a) for b in range(n_b)}

    _add_volume_constraints(model, x, assignments, blocks)
    _add_class_and_teacher_limits(model, x, assignments, n_b)
    _add_teacher_unavailability(model, x, assignments, teacher_unavailabilities, n_b)
    _add_segment_contiguity(model, x, n_a, blocks)
    _add_objective(model, x, assignments, blocks, slot_duration_minutes, preferred_blocks)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVER_SECONDS
    status = solver.solve(model)

    if status == cp_model.MODEL_INVALID:
        raise RuntimeError("CP-SAT rejected the timetable model")
    if status == cp_model.UNKNOWN:
        return GeneratorResult(feasible=False, timed_out=True)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return GeneratorResult(feasible=False)

    merged = _extract_slots(solver, x, assignments, blocks)
    return GeneratorResult(feasible=True, merged_slots=join_adjacent_lessons(merged, assignments))


def _add_volume_constraints(
    model: cp_model.CpModel,
    x: XVars,
    assignments: list[Assignment],
    blocks: list[SlotBlock],
) -> None:
    """Every minute required by each subject must be scheduled, never rounded."""
    n_b = len(blocks)
    for a, asg in enumerate(assignments):
        total_minutes = asg.minutes_per_week
        if asg.partial:
            model.add(sum(x[a, b] for b in range(n_b)) == 1)
            for b, blk in enumerate(blocks):
                if blk.end_minutes - blk.start_minutes < total_minutes:
                    model.add(x[a, b] == 0)
            continue
        model.add(
            sum((blk.end_minutes - blk.start_minutes) * x[a, b] for b, blk in enumerate(blocks))
            == total_minutes
        )


def _add_class_and_teacher_limits(
    model: cp_model.CpModel,
    x: XVars,
    assignments: list[Assignment],
    n_b: int,
) -> None:
    """A class, and each teacher, has at most one course per block."""
    n_a = len(assignments)
    for b in range(n_b):
        model.add(sum(x[a, b] for a in range(n_a)) <= 1)

    for tid in {asg.teacher_id for asg in assignments}:
        teacher_asgs = [a for a, asg in enumerate(assignments) if asg.teacher_id == tid]
        for b in range(n_b):
            model.add(sum(x[a, b] for a in teacher_asgs) <= 1)


def _add_teacher_unavailability(
    model: cp_model.CpModel,
    x: XVars,
    assignments: list[Assignment],
    teacher_unavailabilities: dict[int, set[int]] | None,
    n_b: int,
) -> None:
    if not teacher_unavailabilities:
        return
    for a, asg in enumerate(assignments):
        for b in teacher_unavailabilities.get(asg.teacher_id, set()):
            if b < n_b:
                model.add(x[a, b] == 0)


def _segments(blocks: list[SlotBlock]) -> dict[tuple[int, int], list[int]]:
    """Group block indices into uninterrupted teaching segments, numbered within each day."""
    segments: dict[tuple[int, int], list[int]] = {}
    number = 0
    previous: SlotBlock | None = None
    for index, block in enumerate(blocks):
        if previous is None or previous.day_index != block.day_index:
            number = 0
        elif previous.end_minutes != block.start_minutes:
            number += 1
        segments.setdefault((block.day_index, number), []).append(index)
        previous = block
    return segments


def _add_segment_contiguity(
    model: cp_model.CpModel,
    x: XVars,
    n_a: int,
    blocks: list[SlotBlock],
) -> None:
    """A subject may resume after a real interruption, but runs once per segment."""
    segments = _segments(blocks)
    for a in range(n_a):
        for segment_indices in segments.values():
            starts = []
            for pos, b in enumerate(segment_indices):
                started = model.new_bool_var(f"start_{a}_{b}")
                if pos == 0:
                    model.add(started == x[a, b])
                else:
                    prev = segment_indices[pos - 1]
                    model.add(started >= x[a, b] - x[a, prev])
                    model.add(started <= x[a, b])
                    model.add(started <= 1 - x[a, prev])
                starts.append(started)
            model.add(sum(starts) <= 1)


def _add_objective(
    model: cp_model.CpModel,
    x: XVars,
    assignments: list[Assignment],
    blocks: list[SlotBlock],
    slot_duration_minutes: int,
    preferred_blocks: dict[int, set[int]] | None,
) -> None:
    """Avoid tiny isolated courses and prefer the teachers' chosen blocks."""
    objective_terms: list = []
    for a in range(len(assignments)):
        for b, blk in enumerate(blocks):
            if blk.end_minutes - blk.start_minutes < slot_duration_minutes:
                objective_terms.append((PREFERRED_BONUS * 5) * x[a, b])

    if preferred_blocks:
        for a, asg in enumerate(assignments):
            pref = preferred_blocks.get(asg.teacher_id, set())
            for b in range(len(blocks)):
                if b in pref:
                    objective_terms.append(-PREFERRED_BONUS * x[a, b])

    if objective_terms:
        model.minimize(sum(objective_terms))


def _extract_slots(
    solver: cp_model.CpSolver,
    x: XVars,
    assignments: list[Assignment],
    blocks: list[SlotBlock],
) -> list[MergedSlot]:
    all_merged: list[MergedSlot] = []
    n_b = len(blocks)
    for a, asg in enumerate(assignments):
        assigned_blocks = [b for b in range(n_b) if solver.value(x[a, b])]
        merged = merge_consecutive_blocks(assigned_blocks, blocks, a)
        if asg.partial:
            start = blocks[assigned_blocks[0]].start_minutes
            merged[0].end_time = minutes_to_time(start + asg.minutes_per_week)
        all_merged.extend(merged)
    return all_merged
