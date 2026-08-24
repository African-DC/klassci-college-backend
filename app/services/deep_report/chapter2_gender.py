"""Chapitre II — lectures par sexe : tableaux 14 à 17.

Les tableaux 14 et 16 reprennent les tranches de moyenne du chapitre I, mais
ventilées fille / garçon et agrégées par niveau : 14 sur l'ensemble des
élèves, 16 sur les seuls affectés. Les tableaux 15 et 17 en donnent la
synthèse par cycle.
"""

from __future__ import annotations

from collections.abc import Callable

from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import (
    BandTally,
    Cycle,
    SexCount,
    cycle_of_level,
)
from app.services.deep_report._types import (
    HeaderGroup,
    ReportRow,
    ReportTable,
)

_SUBSIDISED = ("affecte", "reaffecte")

_GENDER_HEADERS = (
    HeaderGroup("Niveau"),
    HeaderGroup("Effectifs réels", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Effectifs classés", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Moy ≥ 10", subs=("F", "G", "T"), align="center"),
    HeaderGroup("08.50 ≤ Moy < 10.00", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Moy < 08.50", subs=("F", "G", "T"), align="center"),
    HeaderGroup("Non classés", subs=("F", "G", "T"), align="center"),
)


def _everyone(_line: StudentLine) -> bool:
    return True


def _subsidised(line: StudentLine) -> bool:
    return line.assignment_status in _SUBSIDISED


def build_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableaux 14 à 17, dans l'ordre du canevas."""
    return (
        _gender_table(
            context,
            number=14,
            title="Récapitulatif par sexe — ensemble des élèves",
            keep=_everyone,
        ),
        _synthesis_table(
            context,
            number=15,
            title="Synthèse genre par cycle — ensemble des élèves",
            keep=_everyone,
        ),
        _gender_table(
            context,
            number=16,
            title="Récapitulatif par sexe — élèves affectés",
            keep=_subsidised,
        ),
        _synthesis_table(
            context,
            number=17,
            title="Synthèse genre par cycle — élèves affectés",
            keep=_subsidised,
        ),
    )


def _gender_table(
    context: ReportContext,
    *,
    number: int,
    title: str,
    keep: Callable[[StudentLine], bool],
) -> ReportTable:
    rows: list[ReportRow] = []
    total = BandTally()

    for level in context.levels:
        lines = [line for line in context.lines_of_level(level.id) if keep(line)]
        tally = _tally_of(lines)
        total = total + tally
        rows.append(ReportRow(cells=_gender_cells(level.name, tally)))

    if rows:
        rows.append(ReportRow(cells=_gender_cells("TOTAL ÉTABLISSEMENT", total), emphasis=True))

    return ReportTable(
        number=number,
        title=title,
        groups=_GENDER_HEADERS,
        rows=tuple(rows),
        empty_message="Aucun niveau renseigné pour cette année scolaire.",
    )


def _gender_cells(label: str, tally: BandTally) -> tuple[str, ...]:
    unranked = SexCount(
        girls=tally.real.girls - tally.ranked.girls,
        boys=tally.real.boys - tally.ranked.boys,
        unknown=tally.real.unknown - tally.ranked.unknown,
    )
    cells: list[str] = [label]
    for count in (
        tally.real,
        tally.ranked,
        tally.passed,
        tally.borderline,
        tally.failed,
        unranked,
    ):
        cells.extend([str(count.girls), str(count.boys), str(count.total)])
    return tuple(cells)


def _synthesis_table(
    context: ReportContext,
    *,
    number: int,
    title: str,
    keep: Callable[[StudentLine], bool],
) -> ReportTable:
    """Effectif par sexe et par cycle, avec le total établissement."""
    per_cycle: dict[Cycle, SexCount] = {Cycle.FIRST: SexCount(), Cycle.SECOND: SexCount()}
    for level in context.levels:
        cycle = cycle_of_level(level.name, level.order)
        for line in context.lines_of_level(level.id):
            if keep(line):
                per_cycle[cycle] = per_cycle[cycle].plus(girl=line.is_girl)

    first = per_cycle[Cycle.FIRST]
    second = per_cycle[Cycle.SECOND]
    overall = first + second

    rows = (
        ReportRow(cells=("F", str(first.girls), str(second.girls), str(overall.girls))),
        ReportRow(cells=("G", str(first.boys), str(second.boys), str(overall.boys))),
        ReportRow(
            cells=(
                "Non renseigné",
                str(first.unknown),
                str(second.unknown),
                str(overall.unknown),
            )
        ),
        ReportRow(
            cells=("Total", str(first.total), str(second.total), str(overall.total)),
            emphasis=True,
        ),
    )

    return ReportTable(
        number=number,
        title=title,
        groups=(
            HeaderGroup("Genre"),
            HeaderGroup("1er cycle", align="center"),
            HeaderGroup("2nd cycle", align="center"),
            HeaderGroup("Total", align="center"),
        ),
        rows=rows,
    )


def _tally_of(lines: list[StudentLine]) -> BandTally:
    tally = BandTally()
    for line in lines:
        tally = tally.with_student(girl=line.is_girl, average=line.average)
    return tally
