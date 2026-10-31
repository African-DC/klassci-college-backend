"""Generateur d'emploi du temps — solveur OR-Tools CP-SAT.

Granularite configurable (ex: 30min, 45min, 60min).
Le solveur travaille en blocs de `slot_duration_minutes` et retourne
des time ranges (start_time, end_time) apres fusion des blocs consecutifs.

Contraintes dures :
- Un enseignant ne peut avoir qu'un seul cours par bloc
- Une classe ne peut avoir qu'un seul cours par bloc
- Chaque assignation obtient le nombre exact de blocs necessaires
- Les indisponibilites enseignant sont respectees
- Les creneaux manuels existants sont preserves
- Pas de cours a cheval sur 2 jours (consecutivite intra-journee)

Contraintes souples :
- Preferer les creneaux marques "preferred" par les enseignants
"""

from dataclasses import dataclass, field
from datetime import time

from ortools.sat.python import cp_model

MAX_SOLVER_SECONDS = 30.0
PREFERRED_BONUS = 10


@dataclass
class Assignment:
    """Assignation prof-matiere pour une classe."""

    teacher_id: int
    subject_id: int
    hours_per_week: int  # total hours (integer)
    minutes_per_week: int | None = None  # remaining minutes after manual courses


@dataclass
class SlotBlock:
    """Un bloc de temps dans la grille du solveur."""

    day: str
    start_minutes: int  # minutes from midnight (e.g., 480 = 08:00)
    end_minutes: int
    day_index: int  # 0=Monday, 1=Tuesday, etc.
    index: int  # global index in the flat list


@dataclass
class FixedBlock:
    """Bloc fixe (slot manuel) — doit etre conserve."""

    assignment_idx: int
    block_idx: int


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
    lesson, not a lost 10:00–11:00 block. Short trailing fragments are retained
    for exact weekly minute totals and penalized by the solver.
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


def solve(
    assignments: list[Assignment],
    blocks: list[SlotBlock],
    slot_duration_minutes: int,
    teacher_unavailabilities: dict[int, set[int]] | None = None,
    fixed_blocks: list[FixedBlock] | None = None,
    preferred_blocks: dict[int, set[int]] | None = None,
    school_blocked: set[int] | None = None,
) -> GeneratorResult:
    """Lance le solveur CP-SAT avec granularite configurable.

    Args:
        assignments: liste d'assignations prof-matiere-heures
        blocks: grille de blocs (construite par build_blocks)
        slot_duration_minutes: duree d'un bloc en minutes
        teacher_unavailabilities: teacher_id -> set d'indices bloques
        fixed_blocks: blocs manuels a conserver
        preferred_blocks: teacher_id -> set d'indices preferes

    Returns:
        GeneratorResult avec merged_slots (creneaux fusionnes prets pour la DB).
    """
    if not assignments or not blocks:
        return GeneratorResult(
            feasible=not any(
                (a.minutes_per_week if a.minutes_per_week is not None else a.hours_per_week * 60)
                > 0
                for a in assignments
            )
        )

    model = cp_model.CpModel()
    n_a = len(assignments)
    n_b = len(blocks)

    # Variables booleennes x[a, b] = 1 si l'assignation a est placee au bloc b
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for a in range(n_a):
        for b in range(n_b):
            x[a, b] = model.new_bool_var(f"x_{a}_{b}")

    # ----- Hard constraints -----

    # Fix manual blocks
    if fixed_blocks:
        for fb in fixed_blocks:
            if 0 <= fb.assignment_idx < n_a and 0 <= fb.block_idx < n_b:
                model.add(x[fb.assignment_idx, fb.block_idx] == 1)

    # Every minute required by each subject must be scheduled, never rounded.
    for a, asg in enumerate(assignments):
        total_minutes = (
            asg.minutes_per_week if asg.minutes_per_week is not None else asg.hours_per_week * 60
        )
        if total_minutes < 0:
            return GeneratorResult(feasible=False)
        model.add(
            sum((blk.end_minutes - blk.start_minutes) * x[a, b] for b, blk in enumerate(blocks))
            == total_minutes
        )

    # School events are hard constraints independent of teachers and subjects.
    for b in school_blocked or set():
        if 0 <= b < n_b:
            for a in range(n_a):
                model.add(x[a, b] == 0)

    # C2: class has at most 1 course per block
    for b in range(n_b):
        model.add(sum(x[a, b] for a in range(n_a)) <= 1)

    # C3: teacher has at most 1 course per block
    teacher_ids = {asg.teacher_id for asg in assignments}
    for tid in teacher_ids:
        teacher_asgs = [a for a, asg in enumerate(assignments) if asg.teacher_id == tid]
        for b in range(n_b):
            model.add(sum(x[a, b] for a in teacher_asgs) <= 1)

    # C4: teacher unavailabilities
    if teacher_unavailabilities:
        for a, asg in enumerate(assignments):
            blocked = teacher_unavailabilities.get(asg.teacher_id, set())
            for b in blocked:
                if b < n_b:
                    model.add(x[a, b] == 0)

    # A subject may resume after a real school interruption. Within each
    # uninterrupted teaching segment, keep at most one continuous course run.
    segments: dict[tuple[int, int], list[int]] = {}
    for b, block in enumerate(blocks):
        previous = blocks[b - 1] if b > 0 else None
        if (
            previous is None
            or previous.day_index != block.day_index
            or previous.end_minutes != block.start_minutes
        ):
            segment_number = (
                0
                if previous is None or previous.day_index != block.day_index
                else max(key[1] for key in segments if key[0] == block.day_index) + 1
            )
        segments.setdefault((block.day_index, segment_number), []).append(b)
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

    # ----- Soft constraints (objective) -----
    objective_terms: list = []

    # Avoid isolated tiny courses whenever whole lessons can satisfy the
    # requested minutes. This is a preference, not a loss of teaching minutes.
    for a in range(n_a):
        for b, blk in enumerate(blocks):
            if blk.end_minutes - blk.start_minutes < slot_duration_minutes:
                objective_terms.append((PREFERRED_BONUS * 5) * x[a, b])

    if preferred_blocks:
        for a, asg in enumerate(assignments):
            pref = preferred_blocks.get(asg.teacher_id, set())
            for b in range(n_b):
                if b in pref:
                    objective_terms.append(-PREFERRED_BONUS * x[a, b])

    if objective_terms:
        model.minimize(sum(objective_terms))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVER_SECONDS
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return GeneratorResult(feasible=False)

    # Extract and merge results
    all_merged: list[MergedSlot] = []
    for a in range(n_a):
        assigned_blocks = [b for b in range(n_b) if solver.value(x[a, b])]
        merged = merge_consecutive_blocks(assigned_blocks, blocks, a)
        all_merged.extend(merged)

    return GeneratorResult(feasible=True, merged_slots=all_merged)
