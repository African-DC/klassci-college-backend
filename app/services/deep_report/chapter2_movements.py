"""Chapitre II — mouvements d'élèves : tableaux 9, 10 et 13.

Qui est arrivé en cours de route (transferts et réintégrations), ce que le
conseil de classe a décidé, et qui bénéficie d'une bourse. Trois tableaux qui
partagent la même exigence : ne jamais présenter une absence de saisie comme
une absence de cas.
"""

from __future__ import annotations

from app.models.deep_report import ScholarshipKind, TransferKind
from app.services.deep_report import _format as fmt
from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import Cycle, SexCount, cycle_of_level
from app.services.deep_report._types import (
    MISSING,
    PENDING_NOTE,
    HeaderGroup,
    ReportRow,
    ReportTable,
    simple_headers,
)

_TRANSFER_LABELS = {
    TransferKind.TRANSFERT.value: "Transfert",
    TransferKind.REINTEGRATION.value: "Réintégration",
}

_SCHOLARSHIP_LABELS = {
    ScholarshipKind.BOURSE_ENTIERE.value: "Bourse entière",
    ScholarshipKind.DEMI_BOURSE.value: "Demi-bourse",
}

# Les décisions telles que KLASSCI les enregistre, dans l'ordre du canevas.
# « Sans décision » n'est pas une décision : c'est l'aveu que le conseil ne
# s'est pas encore prononcé, et il doit rester visible.
_DECISION_COLUMNS = (
    ("Passage", "passage"),
    ("Repêchage", "repechage"),
    ("Redoublement", "redoublement"),
    ("Exclusion", "exclusion"),
)


def _enum_value(raw: object) -> str:
    return str(getattr(raw, "value", raw))


def transfers_table(context: ReportContext) -> ReportTable:
    """Tableau 9 — transferts et réintégrations de l'année.

    Deux sources se complètent. Le mouvement enregistré comme tel fait foi ;
    à défaut, on reprend l'établissement d'origine porté sur la fiche de
    l'élève, saisi pour la demande de dossier scolaire. Ignorer cette
    seconde source laisserait le tableau vide alors que le secrétariat a
    déjà tapé l'information.
    """
    rows: list[ReportRow] = []
    recorded: set[int] = set()

    for transfer, line in context.transfers:
        recorded.add(line.enrollment.id)
        rows.append(
            ReportRow(
                cells=(
                    "",
                    line.full_name,
                    fmt.text(transfer.origin_school),
                    line.class_.name,
                    fmt.text(transfer.decision_number),
                    _TRANSFER_LABELS.get(_enum_value(transfer.kind), MISSING),
                )
            )
        )

    inferred = 0
    for line in context.lines:
        if line.enrollment.id in recorded:
            continue
        origin = (line.student.previous_school or "").strip()
        if not origin:
            continue
        inferred += 1
        rows.append(
            ReportRow(
                cells=(
                    "",
                    line.full_name,
                    origin,
                    line.class_.name,
                    fmt.text(line.student.transfer_decision_number),
                    f"{_TRANSFER_LABELS[TransferKind.TRANSFERT.value]} (fiche élève)",
                )
            )
        )

    numbered = tuple(
        ReportRow(cells=(str(index), *row.cells[1:])) for index, row in enumerate(rows, start=1)
    )

    note = None
    if inferred:
        note = (
            f"{inferred} ligne(s) déduite(s) de l'établissement d'origine porté sur la "
            "fiche de l'élève, faute de mouvement enregistré : vérifier la nature et le "
            "numéro de décision avant dépôt."
        )

    return ReportTable(
        number=9,
        title="Transferts et réintégrations",
        groups=simple_headers(
            "N°",
            "Nom et Prénoms",
            "Établissement d'origine",
            "Classe",
            "N° de décision",
            "Nature",
        ),
        rows=numbered,
        note=note,
        empty_message=(
            "Aucun transfert ni réintégration enregistré sur l'année — "
            f"{PENDING_NOTE.lower()} le cas échéant."
        ),
    )


def council_table(context: ReportContext) -> ReportTable:
    """Tableau 10 — situation après conseil de classe, par niveau puis par cycle."""
    groups = (
        HeaderGroup("Niveau"),
        HeaderGroup("Effectifs", subs=("F", "G", "T"), align="center"),
        *(
            HeaderGroup(label, subs=("F", "G", "T"), align="center")
            for label, _key in _DECISION_COLUMNS
        ),
        HeaderGroup("Sans décision", subs=("F", "G", "T"), align="center"),
    )

    rows: list[ReportRow] = []
    per_cycle: dict[Cycle, list[StudentLine]] = {Cycle.FIRST: [], Cycle.SECOND: []}

    for level in context.levels:
        lines = context.lines_of_level(level.id)
        rows.append(ReportRow(cells=_council_cells(level.name, lines)))
        per_cycle[cycle_of_level(level.name, level.order)].extend(lines)

    for cycle, label in ((Cycle.FIRST, "Total 1er cycle"), (Cycle.SECOND, "Total 2nd cycle")):
        rows.append(ReportRow(cells=_council_cells(label, per_cycle[cycle]), emphasis=True))

    rows.append(ReportRow(cells=_council_cells("TOTAL GÉNÉRAL", context.lines), emphasis=True))

    undecided = sum(1 for line in context.lines if line.council_decision is None)
    note = None
    if undecided:
        note = (
            f"{undecided} élève(s) sans décision de conseil enregistrée : ils apparaissent "
            "en colonne « Sans décision » et non répartis d'office dans une décision."
        )

    return ReportTable(
        number=10,
        title="Situation après conseil de classe",
        groups=groups,
        rows=tuple(rows),
        note=note,
        empty_message="Aucun niveau renseigné pour cette année scolaire.",
    )


def _council_cells(label: str, lines: list[StudentLine]) -> tuple[str, ...]:
    """Effectif puis une ventilation F/G/T par décision de conseil."""
    counts: dict[str, SexCount] = {key: SexCount() for _label, key in _DECISION_COLUMNS}
    counts["_none"] = SexCount()
    headcount = SexCount()

    for line in lines:
        headcount = headcount.plus(girl=line.is_girl)
        key = line.council_decision or "_none"
        if key not in counts:
            # Une décision inconnue du canevas ne doit pas disparaître :
            # faute de colonne dédiée, elle rejoint « sans décision ».
            key = "_none"
        counts[key] = counts[key].plus(girl=line.is_girl)

    cells: list[str] = [label, *_triplet(headcount)]
    for _label, key in _DECISION_COLUMNS:
        cells.extend(_triplet(counts[key]))
    cells.extend(_triplet(counts["_none"]))
    return tuple(cells)


def _triplet(count: SexCount) -> list[str]:
    return [str(count.girls), str(count.boys), str(count.total)]


def scholarships_table(context: ReportContext) -> ReportTable:
    """Tableau 13 — boursiers et demi-boursiers."""
    rows: list[ReportRow] = []
    for index, (scholarship, line) in enumerate(context.scholarships, start=1):
        amount = scholarship.amount
        rows.append(
            ReportRow(
                cells=(
                    str(index),
                    fmt.text(line.student.enrollment_number),
                    line.full_name,
                    fmt.sex(line.is_girl),
                    fmt.day(line.birth_date),
                    line.class_.name,
                    _SCHOLARSHIP_LABELS.get(_enum_value(scholarship.kind), MISSING),
                    fmt.text(scholarship.provider),
                    fmt.text(scholarship.decision_number),
                    f"{amount:,.0f}".replace(",", " ") if amount is not None else MISSING,
                    fmt.text(scholarship.observations),
                )
            )
        )

    return ReportTable(
        number=13,
        title="Boursiers et demi-boursiers",
        groups=simple_headers(
            "N°",
            "Matricule",
            "Nom et Prénoms",
            "Sexe",
            "Date de naissance",
            "Classe",
            "Nature de la bourse",
            "Organisme",
            "N° de décision",
            "Montant (F CFA)",
            "Observations",
        ),
        rows=tuple(rows),
        # Aucun écran ne saisit encore de bourse : sans ligne, on ne sait rien,
        # et « rien » n'est pas « aucun boursier ».
        pending=not rows,
        empty_message=(
            f"Aucune bourse enregistrée sur l'année — {PENDING_NOTE.lower()} le cas échéant."
        ),
    )
