"""Mise en forme des valeurs du rapport DEEP.

Un seul endroit décide de ce qui s'affiche quand une donnée manque, pour que
le document ne mélange jamais « vide », « 0 » et « néant » d'un tableau à
l'autre.
"""

from __future__ import annotations

from datetime import date

from app.services.deep_report._types import MISSING


def text(value: str | None) -> str:
    """Chaîne affichable, ou « — » si elle est absente ou vide."""
    if value is None:
        return MISSING
    cleaned = value.strip()
    return cleaned or MISSING


def day(value: date | None) -> str:
    """Date au format jour/mois/année."""
    return value.strftime("%d/%m/%Y") if value else MISSING


def days(values: list[date]) -> str:
    """Liste de dates séparées par des virgules, triée."""
    if not values:
        return MISSING
    return ", ".join(day(value) for value in sorted(values))


def count(value: int) -> str:
    """Un décompte réellement constaté — le zéro y est une information."""
    return str(value)


def sex(is_girl: bool | None) -> str:
    """Colonne « sexe » du canevas : F, G, ou « — » si non renseigné."""
    if is_girl is None:
        return MISSING
    return "F" if is_girl else "G"


def repeater(is_repeater: bool | None) -> str:
    """Colonne « Qualité » : redoublant ou non, « — » si l'historique manque."""
    if is_repeater is None:
        return MISSING
    return "Red" if is_repeater else "Non Red"


_ASSIGNMENT_LABELS = {
    "affecte": "Aff",
    "reaffecte": "Réaff",
    "non_affecte": "Non Aff",
}


def assignment(status: str | None) -> str:
    """Colonne « Statut » : affecté, réaffecté, non affecté."""
    if status is None:
        return MISSING
    return _ASSIGNMENT_LABELS.get(status, status)
