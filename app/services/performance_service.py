"""Service — score de performance enseignant + activité personnel.

Modèle de score enseignant (transparent, 3 axes pondérés) :

  Assiduité (40%)  — pointage des séances : présent/retard/absence.
  Notes     (35%)  — taux de saisie des notes sur les évaluations créées.
  Appel     (25%)  — part des séances planifiées où l'appel élève a été fait.

Chaque axe est marqué « données insuffisantes » plutôt que noté 0 quand
KLASSCI n'a rien à mesurer (aucune séance pointée, aucune évaluation, aucun
créneau planifié). Le score global n'agrège que les axes suffisants, repondérés
entre eux. Un enseignant sans aucune donnée n'a PAS de score (`None`) — on ne
fabrique pas un chiffre trompeur.

Les résultats des élèves (moyennes de classe) sont volontairement EXCLUS : un
enseignant ne doit pas être noté sur le niveau de ses élèves (équité).

Le personnel n'a pas de score : uniquement un tableau d'activité factuel.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear
from app.repositories import performance_repository as repo
from app.schemas.performance import (
    PerformanceAxis,
    PerformanceSummary,
    StaffActivityItem,
    StaffActivityListResponse,
    TeacherPerformanceItem,
    TeacherPerformanceListResponse,
    TeacherSelfPerformanceResponse,
)

# Pondérations des axes (somme = 1.0)
_WEIGHT_ASSIDUITE = 0.40
_WEIGHT_NOTES = 0.35
_WEIGHT_APPEL = 0.25

# Poids qualitatifs des statuts de pointage pour l'axe assiduité
_ASSIDUITE_STATUS_WEIGHT = {
    "present": 1.0,
    "late": 0.8,
    "absent_excused": 0.6,
    "absent_unexcused": 0.0,
}

# Jours de la semaine indexés comme date.weekday() (lundi=0)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


# ---------------------------------------------------------------------------
# Calendrier — projection des séances planifiées (axe appel)
# ---------------------------------------------------------------------------


def _in_session(day: date, trimesters: list) -> bool:
    """True si le jour tombe dans un trimestre. Sans trimestre défini → True."""
    if not trimesters:
        return True
    return any(t.start_date <= day <= t.end_date for t in trimesters)


def _in_holiday(day: date, holidays: list) -> bool:
    return any(h.start_date <= day <= h.end_date for h in holidays)


def _teaching_weekday_counts(ay: AcademicYear, today: date) -> Counter:
    """Compte, par jour de semaine, le nombre de jours d'enseignement écoulés.

    Un jour compte s'il est dans un trimestre, hors congé, et <= aujourd'hui.
    """
    counts: Counter = Counter()
    end = min(today, ay.end_date)
    current = ay.start_date
    while current <= end:
        if _in_session(current, ay.trimesters) and not _in_holiday(current, ay.holidays):
            counts[_WEEKDAYS[current.weekday()]] += 1
        current += timedelta(days=1)
    return counts


# ---------------------------------------------------------------------------
# Composition des axes enseignant
# ---------------------------------------------------------------------------


def _rating(global_score: float | None, sufficient: bool) -> str:
    if not sufficient or global_score is None:
        return "insuffisant_donnees"
    if global_score >= 80:
        return "excellent"
    if global_score >= 60:
        return "bon"
    return "a_ameliorer"


def _axis_assiduite(counts: dict[str, int], late_minutes: int, pending: int) -> PerformanceAxis:
    present = counts.get("present", 0)
    late = counts.get("late", 0)
    excused = counts.get("absent_excused", 0)
    unexcused = counts.get("absent_unexcused", 0)
    total = present + late + excused + unexcused

    if total == 0:
        return PerformanceAxis(
            key="assiduite",
            label="Assiduité",
            weight=_WEIGHT_ASSIDUITE,
            score=None,
            sufficient=False,
            detail={"total_sessions": 0},
        )

    weighted = (
        present * _ASSIDUITE_STATUS_WEIGHT["present"]
        + late * _ASSIDUITE_STATUS_WEIGHT["late"]
        + excused * _ASSIDUITE_STATUS_WEIGHT["absent_excused"]
        + unexcused * _ASSIDUITE_STATUS_WEIGHT["absent_unexcused"]
    )
    score = round(100.0 * weighted / total, 1)
    return PerformanceAxis(
        key="assiduite",
        label="Assiduité",
        weight=_WEIGHT_ASSIDUITE,
        score=score,
        sufficient=True,
        detail={
            "total_sessions": total,
            "present": present,
            "late": late,
            "absent_excused": excused,
            "absent_unexcused": unexcused,
            "late_minutes": late_minutes,
            "pending_validation": pending,
        },
    )


def _axis_notes(
    eval_class_ids: list[int],
    eval_ids: list[int],
    enrolled_by_class: dict[int, int],
    entered_by_eval: dict[int, int],
) -> PerformanceAxis:
    total_evaluations = len(eval_ids)
    if total_evaluations == 0:
        return PerformanceAxis(
            key="notes",
            label="Saisie des notes",
            weight=_WEIGHT_NOTES,
            score=None,
            sufficient=False,
            detail={"total_evaluations": 0},
        )

    expected_total = 0
    entered_total = 0
    fully_graded = 0
    for eval_id, class_id in zip(eval_ids, eval_class_ids, strict=True):
        expected = enrolled_by_class.get(class_id, 0)
        entered = entered_by_eval.get(eval_id, 0)
        expected_total += expected
        entered_total += entered
        if expected > 0 and entered >= expected:
            fully_graded += 1

    if expected_total == 0:
        # Évaluations créées mais aucune classe avec élèves inscrits → indéterminable.
        return PerformanceAxis(
            key="notes",
            label="Saisie des notes",
            weight=_WEIGHT_NOTES,
            score=None,
            sufficient=False,
            detail={"total_evaluations": total_evaluations, "expected_grades": 0},
        )

    completion = min(1.0, entered_total / expected_total)
    score = round(100.0 * completion, 1)
    return PerformanceAxis(
        key="notes",
        label="Saisie des notes",
        weight=_WEIGHT_NOTES,
        score=score,
        sufficient=True,
        detail={
            "total_evaluations": total_evaluations,
            "fully_graded": fully_graded,
            "entered_grades": entered_total,
            "expected_grades": expected_total,
            "pending_grades": expected_total - entered_total,
        },
    )


def _axis_appel(appels_taken: int, expected_sessions: int) -> PerformanceAxis:
    if expected_sessions == 0:
        return PerformanceAxis(
            key="appel",
            label="Prise de l'appel",
            weight=_WEIGHT_APPEL,
            score=None,
            sufficient=False,
            detail={"appels_taken": appels_taken, "expected_sessions": 0},
        )
    rate = min(1.0, appels_taken / expected_sessions)
    score = round(100.0 * rate, 1)
    return PerformanceAxis(
        key="appel",
        label="Prise de l'appel",
        weight=_WEIGHT_APPEL,
        score=score,
        sufficient=True,
        detail={"appels_taken": appels_taken, "expected_sessions": expected_sessions},
    )


def _compose_global(axes: list[PerformanceAxis]) -> tuple[float | None, bool]:
    sufficient_axes = [a for a in axes if a.sufficient and a.score is not None]
    if not sufficient_axes:
        return None, False
    weight_sum = sum(a.weight for a in sufficient_axes)
    weighted = sum(a.score * a.weight for a in sufficient_axes)  # type: ignore[misc]
    return round(weighted / weight_sum, 1), True


# ---------------------------------------------------------------------------
# Point d'entrée — score de tous les enseignants
# ---------------------------------------------------------------------------


async def _build_teacher_items(db: AsyncSession, ay: AcademicYear) -> list[TeacherPerformanceItem]:
    teachers = await repo.list_teachers(db)
    if not teachers:
        return []

    # Agrégations groupées (une passe pour tous les enseignants)
    assiduite = await repo.assiduite_counts_by_teacher(db, ay.id)
    late_minutes = await repo.late_minutes_by_teacher(db, ay.id)
    pending = await repo.pending_validation_by_teacher(db)
    evaluations = await repo.evaluations_for_year(db, ay.id)
    enrolled_by_class = await repo.enrolled_counts_by_class(db, ay.id)
    entered_by_eval = await repo.entered_grades_by_evaluation(db, ay.id)
    appels_by_user = await repo.appels_taken_by_user(db, ay.id)
    slots = await repo.teacher_slots_for_year(db, ay.id)

    # Regroupe les évaluations par enseignant
    evals_by_teacher: dict[int, tuple[list[int], list[int]]] = {}
    for teacher_id, eval_id, class_id in evaluations:
        eids, cids = evals_by_teacher.setdefault(teacher_id, ([], []))
        eids.append(eval_id)
        cids.append(class_id)

    # Séances attendues par enseignant : classes distinctes par jour de semaine
    classes_by_teacher_day: dict[int, dict[str, set[int]]] = {}
    for teacher_id, day, class_id in slots:
        classes_by_teacher_day.setdefault(teacher_id, {}).setdefault(day, set()).add(class_id)
    teaching_counts = _teaching_weekday_counts(ay, date.today())

    items: list[TeacherPerformanceItem] = []
    for teacher in teachers:
        axis_a = _axis_assiduite(
            assiduite.get(teacher.id, {}),
            late_minutes.get(teacher.id, 0),
            pending.get(teacher.id, 0),
        )

        eids, cids = evals_by_teacher.get(teacher.id, ([], []))
        axis_n = _axis_notes(cids, eids, enrolled_by_class, entered_by_eval)

        expected_sessions = 0
        for day, class_ids in classes_by_teacher_day.get(teacher.id, {}).items():
            expected_sessions += teaching_counts.get(day, 0) * len(class_ids)
        appels_taken = appels_by_user.get(teacher.user_id, 0) if teacher.user_id else 0
        axis_p = _axis_appel(appels_taken, expected_sessions)

        axes = [axis_a, axis_n, axis_p]
        global_score, sufficient = _compose_global(axes)
        items.append(
            TeacherPerformanceItem(
                teacher_id=teacher.id,
                user_id=teacher.user_id,
                first_name=teacher.first_name,
                last_name=teacher.last_name,
                speciality=teacher.speciality,
                photo_url=teacher.photo_url,
                global_score=global_score,
                rating=_rating(global_score, sufficient),
                sufficient=sufficient,
                axes=axes,
            )
        )
    return items


async def get_teachers_performance(db: AsyncSession) -> TeacherPerformanceListResponse:
    ay = await _require_current_year(db)
    items = await _build_teacher_items(db, ay)

    scored = [it for it in items if it.sufficient and it.global_score is not None]
    avg = round(sum(it.global_score for it in scored) / len(scored), 1) if scored else None  # type: ignore[misc]

    staff = await repo.list_staff(db)
    payment_activity = await repo.payment_activity_by_user(db, ay.start_date)
    enrollment_activity = await repo.enrollment_activity_by_user(db, ay.start_date)
    active_staff = sum(
        1 for s in staff if payment_activity.get(s.user_id) or enrollment_activity.get(s.user_id)
    )

    summary = PerformanceSummary(
        teachers_total=len(items),
        teachers_scored=len(scored),
        teachers_insufficient=len(items) - len(scored),
        teachers_avg_score=avg,
        staff_total=len(staff),
        staff_active=active_staff,
    )
    return TeacherPerformanceListResponse(
        academic_year_id=ay.id,
        academic_year_name=ay.name,
        teachers=items,
        summary=summary,
    )


async def get_teacher_self_performance(
    db: AsyncSession, user_id: int
) -> TeacherSelfPerformanceResponse:
    ay = await _require_current_year(db)
    teacher = await repo.get_teacher_by_user_id(db, user_id)
    if teacher is None:
        raise BusinessValidationError("Aucun profil enseignant trouvé pour cet utilisateur.")

    items = await _build_teacher_items(db, ay)
    mine = next((it for it in items if it.teacher_id == teacher.id), None)
    if mine is None:  # cohérence : le teacher existe forcément dans la liste
        raise BusinessValidationError("Impossible de calculer votre performance.")
    return TeacherSelfPerformanceResponse(
        academic_year_id=ay.id,
        academic_year_name=ay.name,
        performance=mine,
    )


# ---------------------------------------------------------------------------
# Personnel — activité factuelle
# ---------------------------------------------------------------------------


async def get_staff_activity(db: AsyncSession) -> StaffActivityListResponse:
    ay = await _require_current_year(db)
    staff = await repo.list_staff(db)
    payment_activity = await repo.payment_activity_by_user(db, ay.start_date)
    enrollment_activity = await repo.enrollment_activity_by_user(db, ay.start_date)

    items: list[StaffActivityItem] = []
    for s in staff:
        count, amount = payment_activity.get(s.user_id, (0, 0))
        items.append(
            StaffActivityItem(
                user_id=s.user_id,
                first_name=s.first_name,
                last_name=s.last_name,
                position=s.position,
                photo_url=s.photo_url,
                payments_count=count,
                payments_amount=float(amount),
                enrollments_count=enrollment_activity.get(s.user_id, 0),
                last_login=s.user.last_login if s.user else None,
            )
        )
    return StaffActivityListResponse(
        academic_year_id=ay.id,
        academic_year_name=ay.name,
        staff=items,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_current_year(db: AsyncSession) -> AcademicYear:
    ay = await repo.get_current_year_with_calendar(db)
    if ay is None:
        raise BusinessValidationError(
            "Aucune année scolaire active. Configurez-en une avant de consulter la performance."
        )
    return ay
