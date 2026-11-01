"""Jours de la semaine de l'emploi du temps, sans dépendance vers les services."""

from enum import Enum
from typing import Any

JOURS_FR = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
}


def day_value(day: Any) -> str:
    """Return the stored day name, whether it is an enum member or already a string."""
    return day.value if isinstance(day, Enum) else day
