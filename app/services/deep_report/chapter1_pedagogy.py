"""Chapitre I — A / Vie pédagogique : visites de classe et formations.

Deux tableaux qui rendent compte de l'encadrement des enseignants pendant le
trimestre. Le canevas agrège par enseignant et par discipline ; KLASSCI
enregistre l'événement unitaire et recompose l'agrégat ici.

Aucun écran ne saisit encore ni visite ni formation : tant que rien n'est
enregistré, les deux tableaux sortent vierges avec la mention d'attente. Un
tableau vide sans mention se lirait « aucune visite ce trimestre », affirmation
que personne ici n'est en mesure de faire.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.services.deep_report import _format as fmt
from app.services.deep_report._context import ReportContext
from app.services.deep_report._types import (
    ReportChapter,
    ReportRow,
    ReportTable,
    simple_headers,
)

# Une école qui n'a rien saisi n'est pas une école sans visites : c'est une
# école qui n'a pas encore renseigné ses visites. Le message le dit.
_NO_VISIT = "Aucune visite de classe enregistrée sur la période — à compléter manuellement."
_NO_TRAINING = "Aucune formation enregistrée sur la période — à compléter manuellement."


def build(context: ReportContext) -> ReportChapter:
    """Assemble les tableaux 1 et 2."""
    return ReportChapter(
        title="Chapitre I — A / Vie pédagogique",
        tables=(_visits_table(context), _trainings_table(context)),
    )


def _visits_table(context: ReportContext) -> ReportTable:
    """Tableau 1 — visites de classe, agrégées par enseignant et discipline."""
    grouped: dict[tuple[str, str], list[date]] = defaultdict(list)
    observations: dict[tuple[str, str], list[str]] = defaultdict(list)

    for visit in context.visits:
        teacher = visit.teacher
        teacher_name = f"{teacher.last_name} {teacher.first_name}".strip()
        discipline = visit.subject.name if visit.subject else (teacher.speciality or "")
        key = (teacher_name, fmt.text(discipline))
        grouped[key].append(visit.visit_date)
        if visit.observations:
            observations[key].append(visit.observations.strip())

    rows: list[ReportRow] = []
    for index, (key, dates) in enumerate(sorted(grouped.items()), start=1):
        teacher_name, discipline = key
        rows.append(
            ReportRow(
                cells=(
                    str(index),
                    teacher_name,
                    discipline,
                    fmt.count(len(dates)),
                    fmt.days(dates),
                    fmt.text(" ; ".join(observations[key])),
                )
            )
        )

    return ReportTable(
        number=1,
        title="Visites de classes",
        groups=simple_headers(
            "N°",
            "Enseignants",
            "Disciplines",
            "Nombre de visites",
            "Dates",
            "Observations",
        ),
        rows=tuple(rows),
        pending=not rows,
        empty_message=_NO_VISIT,
    )


def _trainings_table(context: ReportContext) -> ReportTable:
    """Tableau 2 — formations, agrégées par discipline."""
    dates_by_discipline: dict[str, list[date]] = defaultdict(list)
    teachers_by_discipline: dict[str, set[str]] = defaultdict(set)
    titles_by_discipline: dict[str, set[str]] = defaultdict(set)
    observations: dict[str, list[str]] = defaultdict(list)

    for training in context.trainings:
        discipline = training.subject.name if training.subject else training.discipline_label
        key = fmt.text(discipline)
        teacher = training.teacher
        dates_by_discipline[key].append(training.training_date)
        teachers_by_discipline[key].add(f"{teacher.last_name} {teacher.first_name}".strip())
        titles_by_discipline[key].add(training.title)
        if training.observations:
            observations[key].append(training.observations.strip())

    rows: list[ReportRow] = []
    for discipline, dates in sorted(dates_by_discipline.items()):
        # « Nombre de formations » compte les intitulés distincts : dix
        # enseignants envoyés au même séminaire, c'est une formation, pas dix.
        rows.append(
            ReportRow(
                cells=(
                    discipline,
                    ", ".join(sorted(teachers_by_discipline[discipline])),
                    fmt.count(len(titles_by_discipline[discipline])),
                    fmt.days(dates),
                    fmt.text(" ; ".join(observations[discipline])),
                )
            )
        )

    return ReportTable(
        number=2,
        title="Formations",
        groups=simple_headers(
            "Disciplines",
            "Enseignants formés",
            "Nombre de formations",
            "Dates",
            "Observations",
        ),
        rows=tuple(rows),
        pending=not rows,
        empty_message=_NO_TRAINING,
    )
