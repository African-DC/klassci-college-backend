"""Générateur d'emploi du temps — solveur OR-Tools CP-SAT.

Reçoit une liste d'assignations (prof + matière + heures/semaine) et
une liste de créneaux disponibles, retourne les paires (assignment_idx, slot_idx)
qui constituent un emploi du temps faisable.

Contraintes dures :
- Un enseignant ne peut avoir qu'un seul cours par créneau horaire
- Une classe ne peut avoir qu'un seul cours par créneau
- Chaque assignation obtient exactement `hours_per_week` créneaux
- Les indisponibilités enseignant sont respectées
- Les créneaux manuels existants sont préservés (fixed assignments)
- Conflits inter-classes : profs et salles déjà occupés ailleurs

Contraintes souples :
- Préférer les créneaux marqués "preferred" par les enseignants
"""

from dataclasses import dataclass, field

from ortools.sat.python import cp_model

MAX_SOLVER_SECONDS = 30.0
PREFERRED_BONUS = 10  # Weight for preferred slot soft constraint


@dataclass
class Assignment:
    """Assignation prof-matière pour une classe."""

    teacher_id: int
    subject_id: int
    hours_per_week: int


@dataclass
class SlotTemplate:
    """Créneau horaire disponible (gabarit hebdomadaire)."""

    day: str
    start_time: object  # datetime.time
    end_time: object  # datetime.time
    room_id: int | None = None


@dataclass
class FixedAssignment:
    """Créneau manuel existant — doit être conservé tel quel."""

    assignment_idx: int
    slot_idx: int


@dataclass
class GeneratorResult:
    """Résultat du solveur."""

    feasible: bool
    assignments: list[tuple[int, int]] = field(default_factory=list)
    # list of (assignment_idx, slot_idx)


def solve(
    assignments: list[Assignment],
    slots: list[SlotTemplate],
    teacher_unavailabilities: dict[int, set[int]],
    fixed_assignments: list[FixedAssignment] | None = None,
    preferred_slots: dict[int, set[int]] | None = None,
) -> GeneratorResult:
    """Lance le solveur CP-SAT.

    Args:
        assignments: liste d'assignations prof-matière-heures
        slots: créneaux horaires disponibles pour la semaine
        teacher_unavailabilities: teacher_id -> set d'indices de slots bloques
        fixed_assignments: créneaux manuels existants a conserver (hard fix)
        preferred_slots: teacher_id -> set d'indices de slots preferes (soft)

    Returns:
        GeneratorResult avec feasible=True et la liste des paires si solution trouvee.
    """
    if not assignments or not slots:
        return GeneratorResult(feasible=False)

    model = cp_model.CpModel()
    n_a = len(assignments)
    n_s = len(slots)

    # Variables booléennes x[a, s] = 1 si l'assignation a est placée au créneau s
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for a in range(n_a):
        for s in range(n_s):
            x[a, s] = model.new_bool_var(f"x_{a}_{s}")

    # ----- Hard constraints -----

    # Count manual hours already fixed per assignment
    fixed_hours: dict[int, int] = {}
    if fixed_assignments:
        for fa in fixed_assignments:
            fixed_hours[fa.assignment_idx] = fixed_hours.get(fa.assignment_idx, 0) + 1
            # Fix this variable to 1
            model.add(x[fa.assignment_idx, fa.slot_idx] == 1)

    # C1: each assignment gets exactly hours_per_week slots (including fixed ones)
    for a, asg in enumerate(assignments):
        model.add(sum(x[a, s] for s in range(n_s)) == asg.hours_per_week)

    # C2: class has at most 1 course per slot
    for s in range(n_s):
        model.add(sum(x[a, s] for a in range(n_a)) <= 1)

    # C3: teacher has at most 1 course per slot
    teacher_ids = {asg.teacher_id for asg in assignments}
    for tid in teacher_ids:
        teacher_asgs = [a for a, asg in enumerate(assignments) if asg.teacher_id == tid]
        for s in range(n_s):
            model.add(sum(x[a, s] for a in teacher_asgs) <= 1)

    # C4: room has at most 1 course per slot
    room_ids = {slots[s].room_id for s in range(n_s) if slots[s].room_id is not None}
    for rid in room_ids:
        room_slots = [s for s in range(n_s) if slots[s].room_id == rid]
        for s in room_slots:
            model.add(sum(x[a, s] for a in range(n_a)) <= 1)

    # C5: teacher unavailabilities (includes cross-class conflicts)
    for a, asg in enumerate(assignments):
        blocked = teacher_unavailabilities.get(asg.teacher_id, set())
        for s in blocked:
            if s < n_s:
                model.add(x[a, s] == 0)

    # ----- Soft constraints (objective) -----
    objective_terms: list[cp_model.LinearExpr] = []

    if preferred_slots:
        for a, asg in enumerate(assignments):
            pref = preferred_slots.get(asg.teacher_id, set())
            if pref:
                for s in range(n_s):
                    if s in pref:
                        # Reward: negative cost for preferred slots
                        objective_terms.append(-PREFERRED_BONUS * x[a, s])

    if objective_terms:
        model.minimize(sum(objective_terms))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = MAX_SOLVER_SECONDS
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return GeneratorResult(feasible=False)

    result_pairs: list[tuple[int, int]] = []
    for a in range(n_a):
        for s in range(n_s):
            if solver.value(x[a, s]):
                result_pairs.append((a, s))

    return GeneratorResult(feasible=True, assignments=result_pairs)
