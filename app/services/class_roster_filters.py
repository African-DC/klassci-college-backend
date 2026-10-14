"""Filtres explicites des listes de classe : champs élèves + inscription courante.

La population de base est TOUJOURS chargée depuis les inscriptions validées
et non archivées de l'année scolaire courante par class_roster_service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from unicodedata import normalize


@dataclass(frozen=True)
class RosterFilters:
    genre: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    nationalities: tuple[str, ...] = ()
    assignment_statuses: tuple[str, ...] = ()
    is_repeater: bool | None = None
    is_new_student: bool | None = None


def _fold(value: str) -> str:
    return "".join(
        char for char in normalize("NFKD", value.casefold().strip()) if not (0x300 <= ord(char) <= 0x36F)
    )


def _age(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def filter_roster_rows(
    rows: list[dict],
    filters: RosterFilters | None = None,
    *,
    today: date | None = None,
) -> list[dict]:
    """Intersections entre critères ; sélections multiples = union dans leur champ.

    Champs inconnus : exclus UNIQUEMENT lorsqu'un filtre sur ce champ est actif.
    On ne traite jamais une affectation absente comme « non affecté », ou une
    qualité inconnue comme « non redoublant ».
    """
    if filters is None:
        return rows
    reference = today or date.today()
    nat = {_fold(value) for value in filters.nationalities}
    assignments = set(filters.assignment_statuses)
    selected: list[dict] = []
    for student in rows:
        if filters.genre and student.get("genre") != filters.genre:
            continue
        if nat and _fold(student.get("nationality") or "") not in nat:
            continue
        if assignments and student.get("assignment_status") not in assignments:
            continue
        if filters.is_repeater is not None and student.get("is_repeater") is not filters.is_repeater:
            continue
        if filters.is_new_student is not None and student.get("is_new_student") is not filters.is_new_student:
            continue
        if filters.age_min is not None or filters.age_max is not None:
            born = student.get("birth_date")
            if not isinstance(born, date):
                continue
            age = _age(born, reference)
            if age < 0 or filters.age_min is not None and age < filters.age_min:
                continue
            if filters.age_max is not None and age > filters.age_max:
                continue
        selected.append(student)
    return selected


def describe_roster_filters(filters: RosterFilters | None) -> str:
    """Libellé humain imprimé sur les documents, pour éviter les listes ambiguës."""
    if not filters:
        return ""
    parts = []
    if filters.genre:
        parts.append("Garçons" if filters.genre == "M" else "Filles")
    if filters.age_min is not None:
        parts.append(f"Âge ≥ {filters.age_min} ans")
    if filters.age_max is not None:
        parts.append(f"Âge ≤ {filters.age_max} ans")
    if filters.nationalities:
        parts.append("Nationalité : " + ", ".join(filters.nationalities))
    if filters.assignment_statuses:
        labels = {"affecte": "Affecté", "reaffecte": "Réaffecté", "non_affecte": "Non affecté"}
        parts.append("Affectation : " + ", ".join(labels.get(v, v) for v in filters.assignment_statuses))
    if filters.is_repeater is not None:
        parts.append("Redoublants" if filters.is_repeater else "Non-redoublants")
    if filters.is_new_student is not None:
        parts.append("Nouveaux élèves" if filters.is_new_student else "Anciens élèves")
    return " · ".join(parts)
