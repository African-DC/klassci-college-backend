"""Tableau premium réutilisable + cell renderer typé.

Exporté via `components.py` (aggregator). Ne pas importer ce module
directement depuis les generators : utiliser
`from app.services.pdf import components as ui`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.pdf._blocks import status_pill
from app.services.pdf._helpers import esc, format_decimal
from app.services.pdf.theme import PDFTheme


def premium_table(
    headers: list[str | dict[str, Any]],
    rows: list[list[Any]],
    *,
    theme: PDFTheme,
    empty_message: str = "Aucune donnée.",
    total_row: list[Any] | None = None,
    col_widths: list[str] | None = None,
) -> str:
    """Tableau zebra + header primary + cellules typées.

    `headers` : list de strings (label simple) OU dicts
        {"label": str, "align": "left|right|center"}.
    `rows` : list de list de cellules. Chaque cellule peut être :
      - string / number → rendue telle quelle (escaped)
      - dict {"value": str, "type": "num|pill|muted|muted-lines|emphasis|html"}
        → rendu typé. `muted-lines` coupe la valeur sur ses retours à la ligne.
    `total_row` : ligne récap (mise en valeur orange/primary). Optionnelle.
    `col_widths` : largeurs fixes des colonnes (ex: ["34%", "11%", ...]) rendues
        via un `<colgroup>` pour caler l'alignement (table-layout est fixe).
    """
    colgroup_html = ""
    if col_widths:
        colgroup_html = (
            "<colgroup>"
            + "".join(f'<col style="width:{esc(w)};"/>' for w in col_widths)
            + "</colgroup>"
        )

    if not rows:
        colspan = len(headers) if headers else 1
        return f"""
        <table class="pdf-table">
            {colgroup_html}
            <tbody><tr><td colspan="{colspan}"
                style="text-align:center; padding:14px; color:var(--muted);">
                {esc(empty_message)}
            </td></tr></tbody>
        </table>
        """

    head_cells: list[str] = []
    for h in headers:
        if isinstance(h, dict):
            align = h.get("align", "left")
            align_style = f"text-align:{align};" if align != "left" else ""
            head_cells.append(f'<th style="{align_style}">{esc(h.get("label", ""))}</th>')
        else:
            head_cells.append(f"<th>{esc(h)}</th>")
    head_html = "<tr>" + "".join(head_cells) + "</tr>"

    body_rows: list[str] = []
    for row in rows:
        cells = "".join(_render_cell(cell) for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")

    total_html = ""
    if total_row:
        cells = "".join(_render_cell(cell) for cell in total_row)
        total_html = f'<tr class="total-row">{cells}</tr>'

    return f"""
    <table class="pdf-table">
        {colgroup_html}
        <thead>{head_html}</thead>
        <tbody>{"".join(body_rows)}{total_html}</tbody>
    </table>
    """


def _render_cell(cell: Any) -> str:
    """Rendu d'une cellule (str/number direct, ou dict typé)."""
    if isinstance(cell, dict):
        cell_type = cell.get("type", "text")
        value = cell.get("value", "")
        if cell_type == "num":
            return f'<td class="num">{esc(value)}</td>'
        if cell_type == "muted":
            return f'<td class="muted">{esc(value)}</td>'
        if cell_type == "muted-lines":
            # Plusieurs lignes dans une cellule, échappées puis coupées ici.
            # Le document appelant pourrait composer le HTML lui-même avec le
            # type « html », mais il porterait alors seul la responsabilité
            # d'échapper un nom venu de la base : la faire ici, une fois, est
            # la seule façon qu'aucun document ne l'oublie.
            lignes = "<br>".join(esc(part) for part in str(value).split("\n"))
            return f'<td class="muted">{lignes}</td>'
        if cell_type == "emphasis":
            return f'<td class="emphasis">{esc(value)}</td>'
        if cell_type == "pill":
            label = cell.get("label")
            return f"<td>{status_pill(value, label=label)}</td>"
        if cell_type == "html":
            return f"<td>{value}</td>"
        if cell_type == "num-emphasis":
            return f'<td class="num emphasis">{esc(value)}</td>'
        return f"<td>{esc(value)}</td>"
    if isinstance(cell, Decimal):
        return f'<td class="num">{format_decimal(cell)}</td>'
    return f"<td>{esc(str(cell)) if cell not in (None, '') else '—'}</td>"
