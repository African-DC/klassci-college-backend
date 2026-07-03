"""Service : composition + génération du cahier de texte de classe (PDF).

Étend l'emploi du temps de la classe sur une période réelle : pour chaque
date de l'intervalle, chaque créneau EDT du jour correspondant produit une
séance datée. Par défaut, la période est la semaine courante (lundi → samedi).

L'EDT est un modèle hebdomadaire récurrent rattaché à une année scolaire. La
projection respecte le calendrier scolaire :
- l'année utilisée est celle à laquelle appartient la période (pas forcément
  l'année « courante ») ;
- seules les dates comprises dans un trimestre produisent des séances ; les
  intervalles hors-trimestre (Noël, Pâques, grandes vacances) sont des congés.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.academic import AcademicYear, Class
from app.models.timetable import DayOfWeek
from app.repositories import timetable_repository
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.pdf import generate_cahier_texte_pdf

# weekday() : lundi=0 … dimanche=6
_DAY_VALUE_BY_WEEKDAY: dict[int, str] = {
    0: DayOfWeek.MONDAY.value,
    1: DayOfWeek.TUESDAY.value,
    2: DayOfWeek.WEDNESDAY.value,
    3: DayOfWeek.THURSDAY.value,
    4: DayOfWeek.FRIDAY.value,
    5: DayOfWeek.SATURDAY.value,
}

_JOUR_FR: dict[int, str] = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche",
}


async def _load_class(db: AsyncSession, class_id: int) -> Class:
    stmt = select(Class).where(Class.id == class_id).options(selectinload(Class.level))
    klass = (await db.execute(stmt)).scalar_one_or_none()
    if klass is None:
        raise NotFoundError("Class", class_id)
    return klass


async def _resolve_academic_year(
    db: AsyncSession, period_start: date, period_end: date
) -> AcademicYear | None:
    """Retourne l'année scolaire à laquelle appartient la période.

    On privilégie l'année qui *contient* la date de début. À défaut, n'importe
    quelle année chevauchant la période. En dernier recours, l'année courante.
    Les trimestres sont chargés (selectinload) pour le filtrage des vacances.
    """
    stmt = (
        select(AcademicYear)
        .options(selectinload(AcademicYear.trimesters))
        .where(AcademicYear.start_date <= period_end, AcademicYear.end_date >= period_start)
        .order_by(AcademicYear.start_date.desc())
    )
    candidates = list((await db.execute(stmt)).scalars().all())
    for ay in candidates:
        if ay.start_date <= period_start <= ay.end_date:
            return ay
    if candidates:
        return candidates[0]
    stmt_current = (
        select(AcademicYear)
        .options(selectinload(AcademicYear.trimesters))
        .where(AcademicYear.is_current.is_(True))
        .limit(1)
    )
    return (await db.execute(stmt_current)).scalar_one_or_none()


def _resolve_period(start: date | None, end: date | None) -> tuple[date, date, bool]:
    """Retourne (start, end, is_default_week). Défaut = semaine courante lun→sam."""
    if start is not None and end is not None:
        if end < start:
            start, end = end, start
        return start, end, False
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    saturday = monday + timedelta(days=5)
    return monday, saturday, True


def _period_label(start: date, end: date, is_default_week: bool) -> str:
    if is_default_week:
        return f"Semaine du {start.strftime('%d/%m')} au {end.strftime('%d/%m/%Y')}"
    return f"du {start.strftime('%d/%m/%Y')} au {end.strftime('%d/%m/%Y')}"


def _in_session(day: date, trimesters: list[Any]) -> bool:
    """True si la date tombe dans un trimestre (jour d'école, pas vacances)."""
    return any(t.start_date <= day <= t.end_date for t in trimesters)


def _teacher_name(slot: Any) -> str:
    teacher = getattr(slot, "teacher", None)
    if teacher is None:
        return ""
    return f"{teacher.first_name} {teacher.last_name}".strip()


def _expand_sessions(
    slots: list[Any], start: date, end: date, trimesters: list[Any]
) -> list[dict[str, Any]]:
    """Développe les créneaux EDT sur chaque date de l'intervalle.

    Si des trimestres sont configurés, seules les dates en cours (dans un
    trimestre) produisent des séances ; les dates de vacances sont ignorées.
    Sans trimestre configuré, toutes les dates de l'intervalle sont retenues.
    """
    slots_by_day: dict[str, list[Any]] = {}
    for slot in slots:
        day_value = slot.day.value if hasattr(slot.day, "value") else slot.day
        slots_by_day.setdefault(day_value, []).append(slot)

    sessions: list[tuple[date, Any, dict[str, Any]]] = []
    current = start
    while current <= end:
        skip_holiday = bool(trimesters) and not _in_session(current, trimesters)
        day_value = _DAY_VALUE_BY_WEEKDAY.get(current.weekday())
        if day_value and not skip_holiday:
            for slot in slots_by_day.get(day_value, []):
                horaire = f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}"
                subject = getattr(slot, "subject", None)
                sessions.append(
                    (
                        current,
                        slot.start_time,
                        {
                            "date_str": current.strftime("%d/%m"),
                            "jour": _JOUR_FR.get(current.weekday(), ""),
                            "horaire": horaire,
                            "matiere": subject.name if subject else "",
                            "enseignant": _teacher_name(slot),
                        },
                    )
                )
        current += timedelta(days=1)

    sessions.sort(key=lambda item: (item[0], item[1]))
    return [payload for _, _, payload in sessions]


def _calendar_notice(
    ay: AcademicYear | None,
    trimesters: list[Any],
    has_slots: bool,
    sessions: list[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> str | None:
    """Message expliquant l'absence de séances (vacances vs hors-calendrier).

    Retourne None quand il y a des séances, ou quand l'absence tient à un EDT
    non renseigné (message générique géré par le générateur).
    """
    if sessions or not has_slots or not trimesters:
        return None
    if ay is not None and period_start <= ay.end_date and period_end >= ay.start_date:
        return "Vacances scolaires"
    return "Période hors de l'année scolaire"


async def get_cahier_texte_pdf(
    db: AsyncSession,
    class_id: int,
    start: date | None = None,
    end: date | None = None,
) -> bytes:
    """Génère le cahier de texte PDF d'une classe pour une période."""
    klass = await _load_class(db, class_id)
    period_start, period_end, is_default_week = _resolve_period(start, end)

    ay = await _resolve_academic_year(db, period_start, period_end)
    trimesters = list(ay.trimesters) if ay is not None else []
    slots = await timetable_repository.list_slots(
        db,
        class_id=class_id,
        academic_year_id=ay.id if ay else None,
    )

    sessions = _expand_sessions(slots, period_start, period_end, trimesters)
    calendar_notice = _calendar_notice(
        ay, trimesters, bool(slots), sessions, period_start, period_end
    )

    class_info = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
    }
    period_label = _period_label(period_start, period_end, is_default_week)

    school = await load_school_settings_for_pdf(db)
    return generate_cahier_texte_pdf(
        school, class_info, period_label, sessions, calendar_notice=calendar_notice
    )
