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
) -> list[SlotBlock]:
    """Construit la grille de blocs pour la semaine."""
    blocks: list[SlotBlock] = []
    idx = 0
    for day_idx, day in enumerate(days):
        start_min = day_start_hour * 60
        end_min = day_end_hour * 60
        t = start_min
        while t + slot_duration_minutes <= end_min:
            blocks.append(SlotBlock(
                day=day,
                start_minutes=t,
                end_minutes=t + slot_duration_minutes,
                day_index=day_idx,
                index=idx,
            ))
            t += slot_duration_minutes
            idx += 1
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
            result.append(MergedSlot(
                assignment_idx=assignment_idx,
                day=current_day,
                start_time=minutes_to_time(current_start),
                end_time=minutes_to_time(current_end),
            ))
            current_day = blk.day
            current_start = blk.start_minutes
            current_end = blk.end_minutes

    # Save last group
    result.append(MergedSlot(
        assignment_idx=assignment_idx,
        day=current_day,
        start_time=minutes_to_time(current_start),
        end_time=minutes_to_time(current_end),
    ))

    return result


def solve(
    assignments: list[Assignment],
    blocks: list[SlotBlock],
    slot_duration_minutes: int,
    teacher_unavailabilities: dict[int, set[int]] | None = None,
    fixed_blocks: list[FixedBlock] | None = None,
    preferred_blocks: dict[int, set[int]] | None = None,
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
        return GeneratorResult(feasible=False)

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

    # C1: each assignment gets exactly (hours_per_week * 60 / slot_duration) blocks
    for a, asg in enumerate(assignments):
        total_minutes = asg.hours_per_week * 60
        num_blocks = total_minutes // slot_duration_minutes
        # If there's a remainder, add 1 extra block (last session slightly shorter)
        if total_minutes % slot_duration_minutes > 0:
            num_blocks += 1
        model.add(sum(x[a, b] for b in range(n_b)) == num_blocks)

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

    # C5: consecutivity — blocks of the same assignment on the same day
    # must be contiguous (no gaps). We enforce: for each assignment,
    # on each day, the assigned blocks form a single contiguous run.
    # This is done by: if block b is assigned and block b+1 is NOT assigned
    # (same day), then no later block on that day can be assigned.
    blocks_by_day: dict[int, list[int]] = {}
    for b_idx, blk in enumerate(blocks):
        blocks_by_day.setdefault(blk.day_index, []).append(b_idx)

    for a in range(n_a):
        for day_idx, day_blocks in blocks_by_day.items():
            if len(day_blocks) < 2:
                continue
            # For contiguity: once you stop, you can't restart on the same day
            # Use auxiliary vars: started[a, day] and stopped[a, day, b]
            # Simpler approach: for each pair (i, j) where i < j and they're
            # not consecutive, if x[a,i]=1 and x[a,j]=1, then all between must be 1
            for i_pos in range(len(day_blocks)):
                for j_pos in range(i_pos + 2, len(day_blocks)):
                    bi = day_blocks[i_pos]
                    bj = day_blocks[j_pos]
                    # If both bi and bj are assigned, all blocks between must be too
                    for k_pos in range(i_pos + 1, j_pos):
                        bk = day_blocks[k_pos]
                        # x[a,bi] + x[a,bj] - 1 <= x[a,bk]
                        # i.e., if both bi and bj are 1, then bk must be 1
                        model.add(x[a, bk] >= x[a, bi] + x[a, bj] - 1)

    # ----- Soft constraints (objective) -----
    objective_terms: list = []

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
