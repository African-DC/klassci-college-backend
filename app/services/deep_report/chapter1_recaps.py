"""Chapitre I — B / Résultats scolaires : récapitulatifs (tableaux 5, 6, 7).

Trois fois la même grille, sur trois périmètres : les affectés, les non
affectés, puis tout le monde. Une ligne par classe, un total par niveau, et
les trois tranches de moyenne du canevas.

Les pourcentages se calculent sur les effectifs **classés**, pas sur les
effectifs réels : un élève sans bulletin n'a pas échoué, il n'a pas été
évalué. Le rapporter dans la tranche « Moy < 08.50 » gonflerait un taux
d'échec que l'inspection lit comme un constat.
"""

from __future__ import annotations

from collections.abc import Callable

from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import BandTally, percentage, sum_tallies
from app.services.deep_report._types import (
    HeaderGroup,
    ReportRow,
    ReportTable,
)

_SUBSIDISED = ("affecte", "reaffecte")

_RECAP_HEADERS = (
    HeaderGroup("Classes"),
    HeaderGroup("Effectifs réels", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Effectifs classés", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Moy ≥ 10", subs=("Nombre", "%"), align="center"),
    HeaderGroup("08.50 ≤ Moy < 10.00", subs=("Nombre", "%"), align="center"),
    HeaderGroup("Moy < 08.50", subs=("Nombre", "%"), align="center"),
)

_PERCENT_NOTE = (
    "Les pourcentages portent sur les effectifs classés (élèves disposant d'une "
    "moyenne trimestrielle), et non sur les effectifs réels."
)


def build_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableaux 5, 6 et 7 dans l'ordre du canevas."""
    return (
        _recap_table(
            context,
            number=5,
            title="Récapitulatif par classe et par niveau — élèves affectés",
            keep=lambda line: line.assignment_status in _SUBSIDISED,
            scoped=True,
        ),
        _recap_table(
            context,
            number=6,
            title="Récapitulatif par classe et par niveau — élèves non affectés",
            keep=lambda line: line.assignment_status == "non_affecte",
            scoped=True,
        ),
        _recap_table(
            context,
            number=7,
            title="Récapitulatif par classe et par niveau — ensemble des élèves",
            keep=lambda _line: True,
            scoped=False,
        ),
    )


def _recap_table(
    context: ReportContext,
    *,
    number: int,
    title: str,
    keep: Callable[[StudentLine], bool],
    scoped: bool,
) -> ReportTable:
    """Construit une des trois variantes du récapitulatif."""
    rows: list[ReportRow] = []
    school_tally = BandTally()

    for level in context.levels:
        level_tallies: list[BandTally] = []
        for class_ in context.classes_of_level(level.id):
            lines = [line for line in context.lines if line.class_.id == class_.id and keep(line)]
            tally = _tally_of(lines)
            level_tallies.append(tally)
            rows.append(ReportRow(cells=_recap_cells(class_.name, tally)))

        level_total = sum_tallies(level_tallies)
        school_tally = school_tally + level_total
        rows.append(
            ReportRow(
                cells=_recap_cells(f"EFF. TOTAL — {level.name}", level_total),
                emphasis=True,
            )
        )

    if rows:
        rows.append(
            ReportRow(cells=_recap_cells("TOTAL ÉTABLISSEMENT", school_tally), emphasis=True)
        )

    return ReportTable(
        number=number,
        title=title,
        groups=_RECAP_HEADERS,
        rows=tuple(rows),
        note=_recap_note(context, scoped=scoped),
        empty_message="Aucune classe renseignée pour cette année scolaire.",
    )


def _tally_of(lines: list[StudentLine]) -> BandTally:
    tally = BandTally()
    for line in lines:
        tally = tally.with_student(girl=line.is_girl, average=line.average)
    return tally


def _recap_cells(label: str, tally: BandTally) -> tuple[str, ...]:
    """Les 13 colonnes du canevas pour un groupe donné."""
    ranked_total = tally.ranked.total
    return (
        label,
        str(tally.real.girls),
        str(tally.real.boys),
        str(tally.real.total),
        str(tally.ranked.girls),
        str(tally.ranked.boys),
        str(ranked_total),
        str(tally.passed.total),
        percentage(tally.passed.total, ranked_total),
        str(tally.borderline.total),
        percentage(tally.borderline.total, ranked_total),
        str(tally.failed.total),
        percentage(tally.failed.total, ranked_total),
    )


def _recap_note(context: ReportContext, *, scoped: bool) -> str:
    """Avertissement sous le tableau, y compris sur les inscriptions hors périmètre."""
    notes = [_PERCENT_NOTE]
    unknown_sex = context.unknown_sex_count
    if unknown_sex:
        notes.append(
            f"{unknown_sex} élève(s) sans sexe renseigné : comptés dans la colonne T, "
            "dans aucune des colonnes F ou G."
        )
    unassigned = context.unassigned_count
    if scoped and unassigned:
        notes.append(
            f"{unassigned} inscription(s) sans statut d'affectation renseigné : elles "
            "figurent au récapitulatif d'ensemble (tableau 7) mais dans aucun des deux "
            "récapitulatifs par statut."
        )
    return " ".join(notes)
