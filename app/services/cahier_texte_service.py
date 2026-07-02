"""Service : composition + génération du cahier de texte de classe (PDF).

Étend l'emploi du temps de la classe sur une période réelle : pour chaque
date de l'intervalle, chaque créneau EDT du jour correspondant produit une
séance datée. Par défaut, la période est la semaine courante (lundi → samedi).
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


def _teacher_name(slot: Any) -> str:
    teacher = getattr(slot, "teacher", None)
    if teacher is None:
        return ""
    return f"{teacher.first_name} {teacher.last_name}".strip()


def _expand_sessions(slots: list[Any], start: date, end: date) -> list[dict[str, Any]]:
    """Développe les créneaux EDT sur chaque date de l'intervalle."""
    slots_by_day: dict[str, list[Any]] = {}
    for slot in slots:
        day_value = slot.day.value if hasattr(slot.day, "value") else slot.day
        slots_by_day.setdefault(day_value, []).append(slot)

    sessions: list[tuple[date, Any, dict[str, Any]]] = []
    current = start
    while current <= end:
        day_value = _DAY_VALUE_BY_WEEKDAY.get(current.weekday())
        if day_value:
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


async def get_cahier_texte_pdf(
    db: AsyncSession,
    class_id: int,
    start: date | None = None,
    end: date | None = None,
) -> bytes:
    """Génère le cahier de texte PDF d'une classe pour une période."""
    klass = await _load_class(db, class_id)
    period_start, period_end, is_default_week = _resolve_period(start, end)

    ay = (
        await db.execute(select(AcademicYear).where(AcademicYear.is_current.is_(True)).limit(1))
    ).scalar_one_or_none()
    slots = await timetable_repository.list_slots(
        db,
        class_id=class_id,
        academic_year_id=ay.id if ay else None,
    )

    sessions = _expand_sessions(slots, period_start, period_end)
    class_info = {
        "class_name": klass.name,
        "level_name": getattr(klass.level, "name", "") if klass.level else "",
    }
    period_label = _period_label(period_start, period_end, is_default_week)

    school = await load_school_settings_for_pdf(db)
    return generate_cahier_texte_pdf(school, class_info, period_label, sessions)
