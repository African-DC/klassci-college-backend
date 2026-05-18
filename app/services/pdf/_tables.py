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
) -> str:
    """Tableau zebra + header primary + cellules typées.

    `headers` : list de strings (label simple) OU dicts
        {"label": str, "align": "left|right|center"}.
    `rows` : list de list de cellules. Chaque cellule peut être :
      - string / number → rendue telle quelle (escaped)
      - dict {"value": str, "type": "num|pill|muted|emphasis|html"} → rendu typé
    `total_row` : ligne récap (mise en valeur orange/primary). Optionnelle.
    """
    if not rows:
        return f"""
        <table class="pdf-table">
            <tbody><tr><td style="text-align:center; padding:14px; color:var(--muted);">
                {esc(empty_message)}
            </td></tr></tbody>
        </table>
        """

    head_cells: list[str] = []
    for h in headers:
        if isinstance(h, dict):
            align = h.get("align", "left")
            align_style = f"text-align:{align};" if align != "left" else ""
            head_cells.append(
                f'<th style="{align_style}">{esc(h.get("label", ""))}</th>'
            )
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
