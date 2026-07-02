"""Cahier de texte — PDF A4 paysage structuré depuis l'emploi du temps.

Restitue, pour une période donnée, la liste datée des séances de la classe
(expansion de l'EDT sur les jours réels) avec deux colonnes larges laissées
VIDES : « Contenu de la séance » et « Travail à faire », à remplir à la main
par l'enseignant après chaque cours.

Document de travail interne : sobre, pas de Cachet Électronique Visible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme


def _cahier_styles() -> str:
    """Styles complémentaires : lignes hautes pour l'écriture manuscrite."""
    return """
    <style>
        .cahier-table { font-size: 9.5px; }
        .cahier-table thead th { text-align: left; }
        .cahier-table tbody td {
            height: 46px; padding-top: 8px; padding-bottom: 8px;
            vertical-align: top;
        }
        .cahier-table td.cell-date { font-weight: 600; color: var(--ink); }
        .cahier-table td.cell-day,
        .cahier-table td.cell-time { color: var(--muted); }
        .cahier-table td.cell-fill { background: var(--soft-bg); }
    </style>
    """


def _colgroup() -> str:
    widths = ["9%", "10%", "13%", "15%", "15%", "24%", "14%"]
    cols = "".join(f'<col style="width:{w}">' for w in widths)
    return f"<colgroup>{cols}</colgroup>"


def _thead() -> str:
    return (
        "<thead><tr>"
        "<th>Date</th><th>Jour</th><th>Horaire</th>"
        "<th>Matière</th><th>Enseignant</th>"
        "<th>Contenu de la séance</th><th>Travail à faire</th>"
        "</tr></thead>"
    )


def _tbody(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return (
            "<tbody><tr>"
            '<td colspan="7" style="text-align:center; padding:18px; color:var(--muted);">'
            "Aucune séance planifiée sur cette période."
            "</td></tr></tbody>"
        )
    rows: list[str] = []
    for s in sessions:
        rows.append(
            "<tr>"
            f'<td class="cell-date">{ui.esc(s.get("date_str", ""))}</td>'
            f'<td class="cell-day">{ui.esc(s.get("jour", ""))}</td>'
            f'<td class="cell-time">{ui.esc(s.get("horaire", ""))}</td>'
            f"<td><strong>{ui.esc(s.get('matiere', ''))}</strong></td>"
            f"<td>{ui.esc(s.get('enseignant', ''))}</td>"
            '<td class="cell-fill">&nbsp;</td>'
            '<td class="cell-fill">&nbsp;</td>'
            "</tr>"
        )
    return f"<tbody>{''.join(rows)}</tbody>"


def generate_cahier_texte_pdf(
    school: dict[str, Any],
    class_info: dict[str, Any],
    period_label: str,
    sessions: list[dict[str, Any]],
) -> bytes:
    """Génère le cahier de texte (paysage A4) — theme école dynamique.

    `class_info` : {class_name, level_name}
    `period_label` : ex. « Semaine du 02/03 au 07/03 2026 »
    `sessions` : [{date_str, jour, horaire, matiere, enseignant}] triées.
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)

    class_name = class_info.get("class_name", "") or ""
    parts = [p for p in (class_name, period_label) if p]
    subtitle = " · ".join(ui.esc(p) for p in parts)

    table = (
        f'<table class="pdf-table cahier-table">{_colgroup()}{_thead()}{_tbody(sessions)}</table>'
    )

    issued_str = datetime.utcnow().strftime("%d/%m/%Y")

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="12mm")}
        {_cahier_styles()}
    </head>
    <body>
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school,
            theme=theme,
            doc_type="CAHIER DE TEXTE",
            doc_subtitle=subtitle,
        )
    }

        {table}

        {
        ui.premium_footer(
            school,
            theme=theme,
            note=f"Document de travail interne — édité le {issued_str}.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
