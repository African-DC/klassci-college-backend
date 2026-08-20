"""Chapitre III — personnel administratif : tableaux 22 et 23.

Le canevas imprime la synthèse administrative sur une grille à fonctions
prédéfinies. KLASSCI stocke la fonction en texte libre : plutôt que de forcer
chaque intitulé dans une case du canevas — et d'en perdre au passage — la
synthèse est produite fonction par fonction, telle que l'école les a
nommées, à reporter ensuite sur la grille officielle.
"""

from __future__ import annotations

from collections import Counter

from app.services.deep_report import _format as fmt
from app.services.deep_report._context import ReportContext
from app.services.deep_report._types import (
    MISSING,
    PENDING_NOTE,
    HeaderGroup,
    ReportRow,
    ReportTable,
    simple_headers,
)

_UNSPECIFIED = "Fonction non renseignée"


def build_tables(context: ReportContext) -> tuple[ReportTable, ...]:
    """Tableaux 22 et 23."""
    return (_staff_table(context), _staff_synthesis_table(context))


def _staff_table(context: ReportContext) -> ReportTable:
    """Tableau 22 — situation nominative du personnel administratif."""
    rows: list[ReportRow] = []
    for index, member in enumerate(context.staff, start=1):
        rows.append(
            ReportRow(
                cells=(
                    str(index),
                    f"{member.last_name} {member.first_name}".strip(),
                    fmt.text(member.position),
                    fmt.text(member.cnps_number),
                    fmt.text(member.teaching_authorization_number),
                    fmt.text(member.phone),
                    MISSING,  # Observations — à porter à la main
                )
            )
        )

    return ReportTable(
        number=22,
        title="Situation du personnel administratif",
        groups=simple_headers(
            "N°",
            "Nom et Prénoms",
            "Fonction",
            "N° CNPS",
            "N° autorisation d'enseigner",
            "Téléphone",
            "Observations",
        ),
        rows=tuple(rows),
        empty_message="Aucun membre du personnel administratif enregistré.",
    )


def _staff_synthesis_table(context: ReportContext) -> ReportTable:
    """Tableau 23 — effectif administratif par fonction."""
    counts = Counter((member.position or "").strip() or _UNSPECIFIED for member in context.staff)

    rows = [ReportRow(cells=(position, str(total))) for position, total in sorted(counts.items())]
    if rows:
        rows.append(ReportRow(cells=("TOTAL", str(sum(counts.values()))), emphasis=True))

    return ReportTable(
        number=23,
        title="Synthèse du personnel administratif",
        groups=(
            HeaderGroup("Fonction"),
            HeaderGroup("Effectif", align="right"),
        ),
        rows=tuple(rows),
        note=(
            "Le canevas officiel attend une grille à fonctions prédéfinies. Les fonctions "
            "ci-dessus sont celles saisies par l'établissement : les reporter sur la grille "
            f"— {PENDING_NOTE.lower()} pour la ventilation par sexe et par statut, non "
            "collectée par KLASSCI."
        ),
        empty_message="Aucun membre du personnel administratif enregistré.",
    )
