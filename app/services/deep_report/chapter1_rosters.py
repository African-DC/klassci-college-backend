"""Chapitre I — B / Résultats scolaires : listes nominatives (tableaux 3, 4, 8).

Le canevas veut une grille par classe, élève par élève, puis la liste des
majors. Deux colonnes réclamées — lieu de naissance et nationalité — ne sont
collectées nulle part dans KLASSCI : elles sortent en « — » avec un
avertissement, plutôt qu'inventées.
"""

from __future__ import annotations

from app.models.academic import Class
from app.services.deep_report import _format as fmt
from app.services.deep_report._context import ReportContext, StudentLine
from app.services.deep_report._metrics import format_average
from app.services.deep_report._types import (
    MISSING,
    PENDING_NOTE,
    HeaderGroup,
    ReportRow,
    ReportTable,
    simple_headers,
)

_SUBSIDISED = ("affecte", "reaffecte")

_CIVIL_NOTE = (
    "Colonnes « Lieu de naissance » et « Nationalité » : ces informations ne sont pas "
    f"collectées par KLASSCI — {PENDING_NOTE.lower()} sur le document imprimé."
)
_HISTORY_NOTE = (
    "Colonne « Qualité » : aucune année scolaire antérieure n'est enregistrée, "
    f"le redoublement ne peut pas être établi — {PENDING_NOTE.lower()}."
)


def roster_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableau 3 — une grille par classe, affectés et non affectés confondus."""
    tables: list[ReportTable] = []
    for level in context.levels:
        for class_ in context.classes_of_level(level.id):
            lines = _class_lines(context, class_)
            tables.append(
                ReportTable(
                    number=3,
                    title="Liste de classe et résultats (affectés et non affectés)",
                    subtitle=class_.name,
                    groups=simple_headers(
                        "N°",
                        "Matricule",
                        "Nom et Prénoms",
                        "Sexe",
                        "Date de naissance",
                        "Lieu de naissance",
                        "Nationalité",
                        "Qualité",
                        "Statut",
                        "N° déci d'Aff.",
                        "Moy Trim",
                        "Rang",
                        "Observations",
                    ),
                    rows=tuple(
                        _student_row(index, line, with_status=True)
                        for index, line in enumerate(lines, start=1)
                    ),
                    note=_roster_note(context),
                    empty_message="Aucun élève inscrit dans cette classe.",
                )
            )
    return tuple(tables)


def subsidised_roster_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableau 4 — même grille, affectés seuls, sans la colonne « Statut »."""
    tables: list[ReportTable] = []
    for level in context.levels:
        for class_ in context.classes_of_level(level.id):
            lines = [line for line in _class_lines(context, class_) if _is_subsidised(line)]
            tables.append(
                ReportTable(
                    number=4,
                    title="Liste de classe et résultats (affectés)",
                    subtitle=class_.name,
                    groups=simple_headers(
                        "N°",
                        "Matricule",
                        "Nom et Prénoms",
                        "Sexe",
                        "Date de naissance",
                        "Lieu de naissance",
                        "Nationalité",
                        "Qualité",
                        "N° déci d'Aff.",
                        "Moy Trim",
                        "Rang",
                        "Observations",
                    ),
                    rows=tuple(
                        _student_row(index, line, with_status=False)
                        for index, line in enumerate(lines, start=1)
                    ),
                    note=_roster_note(context),
                    empty_message=(
                        "Aucun élève affecté dans cette classe, ou statut d'affectation "
                        "non renseigné."
                    ),
                )
            )
    return tuple(tables)


def top_students_table(context: ReportContext) -> ReportTable:
    """Tableau 8 — le major de chaque classe, à la meilleure moyenne du trimestre."""
    rows: list[ReportRow] = []
    for level in context.levels:
        for class_ in context.classes_of_level(level.id):
            ranked = [line for line in _class_lines(context, class_) if line.average is not None]
            if not ranked:
                continue
            # À moyenne égale, le rang du bulletin départage ; sans rang, le
            # premier de la liste alphabétique. On ne tire jamais au hasard.
            major = min(
                ranked,
                key=lambda line: (
                    -(line.average or 0),
                    line.rank if line.rank is not None else 10**6,
                    line.full_name,
                ),
            )
            rows.append(
                ReportRow(
                    cells=(
                        class_.name,
                        fmt.text(major.student.enrollment_number),
                        major.full_name,
                        fmt.sex(major.is_girl),
                        fmt.day(major.birth_date),
                        MISSING,  # Lieu de naissance — non collecté
                        MISSING,  # Nationalité — non collectée
                        fmt.assignment(major.assignment_status),
                        format_average(major.average),
                        str(major.rank) if major.rank is not None else MISSING,
                    )
                )
            )

    return ReportTable(
        number=8,
        title="Majors de classe",
        groups=(
            HeaderGroup("Classe"),
            HeaderGroup("Matricule"),
            HeaderGroup("Nom et Prénoms"),
            HeaderGroup("Sexe", align="center"),
            HeaderGroup("Date de naissance"),
            HeaderGroup("Lieu de naissance"),
            HeaderGroup("Nationalité"),
            HeaderGroup("Statut", align="center"),
            HeaderGroup("Moyenne", align="right"),
            HeaderGroup("Rang", align="right"),
        ),
        rows=tuple(rows),
        note=_CIVIL_NOTE,
        empty_message=(
            "Aucune moyenne trimestrielle disponible : les majors ne peuvent pas être "
            f"désignés — {PENDING_NOTE.lower()}."
        ),
    )


def _class_lines(context: ReportContext, class_: Class) -> list[StudentLine]:
    """Élèves d'une classe, triés par nom comme sur la liste officielle."""
    return sorted(
        (line for line in context.lines if line.class_.id == class_.id),
        key=lambda line: (line.student.last_name.lower(), line.student.first_name.lower()),
    )


def _is_subsidised(line: StudentLine) -> bool:
    return line.assignment_status in _SUBSIDISED


def _student_row(index: int, line: StudentLine, *, with_status: bool) -> ReportRow:
    """Une ligne nominative du canevas, avec ou sans la colonne « Statut »."""
    cells: list[str] = [
        str(index),
        fmt.text(line.student.enrollment_number),
        line.full_name,
        fmt.sex(line.is_girl),
        fmt.day(line.birth_date),
        MISSING,  # Lieu de naissance — non collecté par KLASSCI
        MISSING,  # Nationalité — non collectée par KLASSCI
        fmt.repeater(line.is_repeater),
    ]
    if with_status:
        cells.append(fmt.assignment(line.assignment_status))
    cells.extend(
        [
            fmt.text(line.enrollment.assignment_decision_number),
            format_average(line.average),
            str(line.rank) if line.rank is not None else MISSING,
            fmt.text(line.enrollment.notes),
        ]
    )
    return ReportRow(cells=tuple(cells))


def _roster_note(context: ReportContext) -> str:
    """Avertissements portés sous chaque grille nominative."""
    notes = [_CIVIL_NOTE]
    if not context.has_history:
        notes.append(_HISTORY_NOTE)
    return " ".join(notes)
