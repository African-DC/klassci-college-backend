"""Exports consolidés d'échéanciers, sans nouvelle lecture financière.

PDF et XLSX reçoivent exactement le même ScheduleOverviewResponse que la
page. Le paramétrage visuel vient de SchoolSettings du tenant.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill

from app.schemas.installment_overview import ScheduleOverviewResponse, ScheduleOverviewRow
from app.services.exports._workbook_branding import (
    set_widths,
    setup_printing,
    style_table_header,
    style_total_row,
    write_header,
)
from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

LABELS = {
    "late": "En retard",
    "on_track": "À jour",
    "settled": "Soldé",
    "unconfigured": "Sans grille",
    "partial_schedule": "Partiellement planifié",
    "no_fees": "Sans frais",
}
SOURCE_LABELS = {
    "standard": "Grille établissement",
    "negotiated": "Accord individuel",
    "none": "Non planifié",
}


def _xof(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ")


def _date(value: Any) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def _headers(
    *,
    year: str,
    class_name: str,
    search: str,
    state: str,
    issued_at: datetime,
) -> list[str]:
    scope = f"Année : {year} · Classe : {class_name or 'Toutes les classes'}"
    filters = [f"Statut : {LABELS.get(state, 'Tous') if state != 'all' else 'Tous'}"]
    if search:
        filters.append(f"Recherche : {search}")
    return [
        scope,
        " · ".join(filters),
        f"Édité le {issued_at.strftime('%d/%m/%Y à %H:%M')} · Montants en FCFA",
        "Les retards sont calculés sur les échéances exigibles à la date d'édition ; "
        "les frais non planifiés n'ont pas de date limite.",
    ]


def generate_overview_xlsx(
    result: ScheduleOverviewResponse,
    school: dict[str, Any],
    *,
    year: str,
    class_name: str,
    search: str,
    state: str,
    issued_at: datetime,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Échéanciers"
    columns = (
        "Élève",
        "Matricule",
        "Classe",
        "Origine",
        "État",
        "Total dû",
        "Versé",
        "Exigible à date",
        "Reste dû",
        "Retard",
        "Prochaine échéance",
        "Montant prochain",
        "Non planifié",
    )
    header = write_header(
        ws,
        school,
        title="SUIVI DES ÉCHÉANCIERS",
        subtitle=f"Année scolaire {year}",
        meta_lines=_headers(
            year=year,
            class_name=class_name,
            search=search,
            state=state,
            issued_at=issued_at,
        ),
        width=len(columns),
    )
    for col, label in enumerate(columns, 1):
        ws.cell(header, col, label)
    style_table_header(ws, header, len(columns), school)

    money_cols = (6, 7, 8, 9, 10, 12, 13)
    for index, row in enumerate(result.items, header + 1):
        values = (
            row.student_name,
            row.matricule or "",
            row.class_name,
            SOURCE_LABELS.get(row.source, row.source),
            LABELS.get(row.state, row.state),
            row.total_due,
            row.total_paid,
            row.due_so_far,
            row.remaining,
            row.late_amount,
            row.next_due_date,
            row.next_due_amount,
            row.unscheduled_amount,
        )
        for col, value in enumerate(values, 1):
            cell = ws.cell(index, col, value)
            # Les noms d'élèves sont des données, jamais des formules Excel
            # même si un import commence par "=" (CSV/formula injection).
            if isinstance(value, str):
                cell.data_type = "s"
            if col in money_cols:
                cell.number_format = '#,##0" F"'
                cell.alignment = Alignment(horizontal="right")
            if col == 11 and value is not None:
                cell.number_format = "DD/MM/YYYY"
            if index % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="FFF4F6FA")

    total_row = header + 1 + len(result.items)
    ws.cell(total_row, 1, "TOTAL")
    ws.cell(total_row, 6, result.totals.total_due)
    ws.cell(total_row, 7, result.totals.total_paid)
    ws.cell(total_row, 9, result.totals.total_remaining)
    ws.cell(total_row, 10, result.totals.total_late)
    for col in money_cols:
        ws.cell(total_row, col).number_format = '#,##0" F"'
    style_total_row(ws, total_row, len(columns), school)
    set_widths(ws, [34, 19, 20, 23, 25, 18, 18, 20, 18, 18, 20, 18, 18])
    ws.freeze_panes = f"D{header + 1}"
    ws.auto_filter.ref = f"A{header}:M{header + len(result.items)}"
    setup_printing(ws, header_row=header)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_row(row: ScheduleOverviewRow) -> list[Any]:
    return [
        row.student_name,
        row.class_name,
        LABELS.get(row.state, row.state),
        {"value": _xof(row.total_due), "type": "num"},
        {"value": _xof(row.total_paid), "type": "num"},
        {"value": _xof(row.remaining), "type": "num"},
        {"value": _xof(row.late_amount), "type": "num-emphasis"},
        _date(row.next_due_date),
    ]


def generate_overview_pdf(
    result: ScheduleOverviewResponse,
    school: dict[str, Any],
    *,
    year: str,
    class_name: str,
    search: str,
    state: str,
    issued_at: datetime,
) -> bytes:
    from weasyprint import HTML  # lazy import : helper pdf_response traite GTK absent

    theme = PDFTheme.from_school(school)
    meta = _headers(
        year=year,
        class_name=class_name,
        search=search,
        state=state,
        issued_at=issued_at,
    )
    table = ui.premium_table(
        headers=[
            "Élève",
            "Classe",
            "État",
            {"label": "Dû", "align": "right"},
            {"label": "Versé", "align": "right"},
            {"label": "Reste", "align": "right"},
            {"label": "Retard", "align": "right"},
            "Prochaine date",
        ],
        rows=[_pdf_row(row) for row in result.items],
        theme=theme,
        empty_message="Aucun échéancier ne correspond aux filtres.",
        total_row=(
            [
                "TOTAL",
                "",
                "",
                {"value": _xof(result.totals.total_due), "type": "num"},
                {"value": _xof(result.totals.total_paid), "type": "num"},
                {"value": _xof(result.totals.total_remaining), "type": "num"},
                {"value": _xof(result.totals.total_late), "type": "num-emphasis"},
                "",
            ]
            if result.items
            else None
        ),
    )
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">{ui.base_styles(theme, page_size="A4 landscape", margin="12mm")}</head>
<body>
{ui.page_decoration(theme=theme, watermark_text=school.get("school_name") or "")}
<div class="pdf-page-body">
{ui.premium_header(school, theme=theme, doc_type="SUIVI DES ÉCHÉANCIERS", doc_subtitle=year)}
{ui.meta_banner(ui.esc(meta[0]), ui.esc(meta[1]), theme=theme)}
{ui.section_title(ui.esc(meta[2]), theme=theme)}
{ui.kpis_row(cards=[
    {"label": "Élèves", "value": str(result.totals.enrollments)},
    {"label": "En retard", "value": str(result.totals.late_enrollments)},
    {"label": "Retard cumulé", "value": _xof(result.totals.total_late) + " F"},
], theme=theme)}
{table}
<p style="font-size:9px;color:#666;margin-top:12px">{ui.esc(meta[3])}</p>
{ui.premium_footer(school, theme=theme, note="État calculé à la date d'édition.")}
</div></body></html>"""
    return HTML(string=html).write_pdf()
