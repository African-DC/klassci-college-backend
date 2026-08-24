"""Chapitre II — pyramides des effectifs : tableaux 11 et 12.

Le canevas imprime ces deux tableaux sur une grille à colonnes fixes, calée
sur un établissement complet de la 6ème à la Terminale. KLASSCI génère les
colonnes à partir des niveaux réellement ouverts : un collège qui s'arrête en
3ème obtient quatre niveaux, pas sept dont trois vides qui laisseraient
croire à des classes fermées.
"""

from __future__ import annotations

from collections import defaultdict

from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import SexCount
from app.services.deep_report._types import (
    HeaderGroup,
    ReportRow,
    ReportTable,
)

_UNKNOWN_YEAR = "Non renseignée"


def pyramid_table(context: ReportContext) -> ReportTable:
    """Tableau 11 — base de la pyramide : effectif F/G par niveau."""
    groups = (
        HeaderGroup("Pyramide"),
        *(HeaderGroup(level.name, subs=("F", "G"), align="center") for level in context.levels),
        HeaderGroup("Total", subs=("F", "G"), align="center"),
    )

    counts = {level.id: SexCount() for level in context.levels}
    for line in context.lines:
        counts[line.level.id] = counts[line.level.id].plus(girl=line.is_girl)

    cells: list[str] = ["BASE"]
    overall = SexCount()
    for level in context.levels:
        count = counts[level.id]
        overall = overall + count
        cells.extend([str(count.girls), str(count.boys)])
    cells.extend([str(overall.girls), str(overall.boys)])

    return ReportTable(
        number=11,
        title="Pyramide des effectifs",
        groups=groups,
        rows=(ReportRow(cells=tuple(cells)),) if context.levels else (),
        note=_unknown_sex_note(context),
        empty_message="Aucun niveau renseigné pour cette année scolaire.",
    )


def birth_year_table(context: ReportContext) -> ReportTable:
    """Tableau 12 — répartition par année de naissance, ventilée F / G / Total.

    Le canevas fusionne les trois lignes d'une même année ; on répète l'année
    sur chacune, ce qui se lit aussi bien à l'impression et évite une cellule
    fusionnée fragile en découpe de page.
    """
    groups = (
        HeaderGroup("Année de naissance"),
        HeaderGroup("Sexe", align="center"),
        *(HeaderGroup(level.name, align="center") for level in context.levels),
        HeaderGroup("Total", align="center"),
    )

    by_year: dict[str, list[StudentLine]] = defaultdict(list)
    for line in context.lines:
        birth = line.birth_date
        by_year[str(birth.year) if birth else _UNKNOWN_YEAR].append(line)

    rows: list[ReportRow] = []
    for year in _sorted_years(by_year):
        lines = by_year[year]
        rows.append(ReportRow(cells=_sex_line(context, year, "F", lines, girl=True)))
        rows.append(ReportRow(cells=_sex_line(context, year, "G", lines, girl=False)))
        rows.append(
            ReportRow(cells=_sex_line(context, year, "Total", lines, girl=None), emphasis=True)
        )

    notes = []
    if _UNKNOWN_YEAR in by_year:
        notes.append(
            f"{len(by_year[_UNKNOWN_YEAR])} élève(s) sans date de naissance renseignée : "
            f"regroupés sur la ligne « {_UNKNOWN_YEAR} » plutôt qu'imputés à une année."
        )
    unknown_sex = _unknown_sex_note(context)
    if unknown_sex:
        notes.append(unknown_sex)

    return ReportTable(
        number=12,
        title="Répartition des effectifs par année de naissance",
        groups=groups,
        rows=tuple(rows),
        note=" ".join(notes) if notes else None,
        empty_message="Aucun élève inscrit pour cette année scolaire.",
    )


def _sorted_years(by_year: dict[str, list[StudentLine]]) -> list[str]:
    """Années de naissance croissantes, les non renseignées en dernier."""
    known = sorted(year for year in by_year if year != _UNKNOWN_YEAR)
    return known + ([_UNKNOWN_YEAR] if _UNKNOWN_YEAR in by_year else [])


def _sex_line(
    context: ReportContext,
    year: str,
    label: str,
    lines: list[StudentLine],
    *,
    girl: bool | None,
) -> tuple[str, ...]:
    """Une ligne du tableau 12. `girl=None` → la ligne « Total » de l'année."""
    selected = lines if girl is None else [line for line in lines if line.is_girl is girl]
    per_level = {level.id: 0 for level in context.levels}
    for line in selected:
        per_level[line.level.id] += 1

    cells: list[str] = [year, label]
    cells.extend(str(per_level[level.id]) for level in context.levels)
    cells.append(str(len(selected)))
    return tuple(cells)


def _unknown_sex_note(context: ReportContext) -> str | None:
    unknown = context.unknown_sex_count
    if not unknown:
        return None
    return (
        f"{unknown} élève(s) sans sexe renseigné : comptés dans les totaux, dans aucune "
        "des colonnes F ou G."
    )
