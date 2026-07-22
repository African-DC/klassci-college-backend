"""Relevé de notes de classe — PDF A4 paysage REMPLI (données réelles).

Contrairement à la feuille de notes vierge (`grade_sheet.py`), ce document
restitue les notes déjà saisies pour une matière, une classe et un trimestre :
une colonne par évaluation, la note de chaque élève, sa moyenne pondérée par
les coefficients d'évaluation et son rang dans la classe.

Document de travail interne (secrétariat, professeur principal, conseil) : sobre,
sans sceau numérique institutionnel ni signature élève.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

_TYPE_LABELS = {
    "controle": "Contrôle",
    "devoir": "Devoir",
    "examen": "Examen",
    "oral": "Oral",
}


def _report_styles() -> str:
    """Styles complémentaires : en-têtes d'évaluation compacts + colonnes notes."""
    return """
    <style>
        .grade-report { font-size: 9px; }
        .grade-report thead th { text-align: center; vertical-align: bottom; }
        .grade-report thead th.col-name { text-align: left; }
        .grade-report thead th.col-moy,
        .grade-report thead th.col-rank { border-bottom-color: var(--accent); }
        .grade-report .eval-title {
            font-weight: 600; display: block; line-height: 1.15;
        }
        .grade-report .eval-sub {
            display: block; font-weight: 400; color: var(--muted);
            font-size: 7.5px; letter-spacing: 0; text-transform: none; margin-top: 2px;
        }
        .grade-report tbody td { vertical-align: middle; }
        .grade-report td.cell-num { text-align: center; color: var(--muted); }
        .grade-report td.cell-mat {
            font-family: 'Courier New', monospace; font-size: 8px; color: var(--muted);
        }
        .grade-report td.cell-note { text-align: center; font-variant-numeric: tabular-nums; }
        .grade-report td.cell-empty { text-align: center; color: var(--muted); }
        .grade-report td.cell-moy {
            text-align: center; font-weight: 700; color: var(--primary);
            background: var(--soft-bg); font-variant-numeric: tabular-nums;
        }
        .grade-report td.cell-rank { text-align: center; color: var(--ink); }
    </style>
    """


def _colgroup(eval_count: int) -> str:
    """Largeurs fixes : N° + Élève + colonnes d'évaluations + Moyenne + Rang."""
    fixed_num = 4
    fixed_name = 22
    fixed_moy = 9
    fixed_rank = 6
    remaining = 100 - fixed_num - fixed_name - fixed_moy - fixed_rank
    eval_width = remaining / eval_count if eval_count else remaining
    cols = [
        f'<col style="width:{fixed_num}%">',
        f'<col style="width:{fixed_name}%">',
    ]
    cols += [f'<col style="width:{eval_width:.3f}%">'] * eval_count
    cols += [f'<col style="width:{fixed_moy}%">', f'<col style="width:{fixed_rank}%">']
    return f"<colgroup>{''.join(cols)}</colgroup>"


def _eval_header_cell(evaluation: dict[str, Any]) -> str:
    """En-tête d'une colonne évaluation : titre court + coef + date."""
    title = str(evaluation.get("title") or "").strip()
    if not title:
        title = _TYPE_LABELS.get(str(evaluation.get("type") or ""), "Évaluation")
    if len(title) > 18:
        title = title[:17].rstrip() + "…"
    coef = evaluation.get("coefficient") or 1
    date_val = evaluation.get("date")
    date_str = date_val.strftime("%d/%m") if hasattr(date_val, "strftime") else ""
    return (
        "<th>"
        f'<span class="eval-title">{ui.esc(title)}</span>'
        f'<span class="eval-sub">coef {ui.esc(coef)} · {ui.esc(date_str)}</span>'
        "</th>"
    )


def _thead(evaluations: list[dict[str, Any]]) -> str:
    eval_cells = "".join(_eval_header_cell(e) for e in evaluations)
    return (
        "<thead><tr>"
        '<th>N°</th><th class="col-name">Élève</th>'
        f"{eval_cells}"
        '<th class="col-moy">Moyenne</th><th class="col-rank">Rang</th>'
        "</tr></thead>"
    )


def _note_cell(value: Any) -> str:
    if value is None:
        return '<td class="cell-empty">—</td>'
    return f'<td class="cell-note">{ui.format_decimal(value)}</td>'


def _student_row(index: int, student: dict[str, Any], eval_count: int) -> str:
    matricule = ui.esc(student.get("enrollment_number") or "—")
    name = ui.esc(student.get("name") or "")
    values = student.get("values") or []
    notes = "".join(_note_cell(v) for v in values)
    # Garde-fou : compléter si moins de valeurs que d'évaluations.
    if len(values) < eval_count:
        notes += '<td class="cell-empty">—</td>' * (eval_count - len(values))
    avg = student.get("average")
    avg_html = ui.format_decimal(avg) if avg is not None else "—"
    rank = student.get("rank")
    rank_html = str(rank) if rank is not None else "—"
    return (
        "<tr>"
        f'<td class="cell-num">{index}</td>'
        f"<td><strong>{name}</strong><br/>"
        f'<span class="cell-mat">{matricule}</span></td>'
        f"{notes}"
        f'<td class="cell-moy">{avg_html}</td>'
        f'<td class="cell-rank">{rank_html}</td>'
        "</tr>"
    )


def _table(evaluations: list[dict[str, Any]], student_rows: list[dict[str, Any]]) -> str:
    eval_count = len(evaluations)
    if eval_count == 0:
        return (
            '<table class="pdf-table grade-report">'
            '<tbody><tr><td style="text-align:center; padding:18px; color:var(--muted);">'
            "Aucune évaluation saisie pour cette matière sur ce trimestre."
            "</td></tr></tbody></table>"
        )
    if not student_rows:
        span = eval_count + 4
        body = (
            "<tbody><tr>"
            f'<td colspan="{span}" style="text-align:center; padding:16px; color:var(--muted);">'
            "Aucun élève inscrit dans cette classe pour l'année courante."
            "</td></tr></tbody>"
        )
    else:
        rows = "".join(_student_row(i, s, eval_count) for i, s in enumerate(student_rows, 1))
        body = f"<tbody>{rows}</tbody>"
    return (
        '<table class="pdf-table grade-report">'
        f"{_colgroup(eval_count)}{_thead(evaluations)}{body}"
        "</table>"
    )


def _stats_band(theme: PDFTheme, class_stats: dict[str, Any]) -> str:
    """Bandeau de synthèse via les cartes KPI premium partagées."""

    def fmt(val: Any) -> str:
        return ui.format_decimal(val) if val is not None else "—"

    fill_rate = class_stats.get("fill_rate")
    fill_str = f"{fill_rate} %" if fill_rate is not None else "—"
    cards = [
        {
            "label": "Moyenne de classe",
            "value": f"{fmt(class_stats.get('class_avg'))} / 20",
            "tone": "accent",
        },
        {"label": "Note min", "value": fmt(class_stats.get("min"))},
        {"label": "Note max", "value": fmt(class_stats.get("max"))},
        {"label": "Taux de saisie", "value": fill_str, "tone": "success"},
    ]
    return ui.kpis_row(cards, theme=theme)


def generate_grade_report_pdf(
    school: dict[str, Any],
    class_info: dict[str, Any],
    subject_name: str,
    trimester: str,
    academic_year_label: str,
    evaluations: list[dict[str, Any]],
    student_rows: list[dict[str, Any]],
    class_stats: dict[str, Any],
) -> bytes:
    """Génère le relevé de notes rempli (paysage A4) — theme école dynamique.

    `class_info` : {class_name, level_name}
    `evaluations` : [{title, type, coefficient, date}] dans l'ordre des colonnes
    `student_rows` : [{name, enrollment_number, values:[Decimal|None], average, rank}]
    `class_stats` : {class_avg, min, max, fill_rate}
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)

    class_name = class_info.get("class_name", "") or ""
    parts = [p for p in (class_name, subject_name, trimester, academic_year_label) if p]
    subtitle = " · ".join(ui.esc(p) for p in parts)

    issued_str = datetime.utcnow().strftime("%d/%m/%Y")
    table = _table(evaluations, student_rows)
    stats = _stats_band(theme, class_stats) if evaluations else ""

    meta_left = f"<strong>Effectif</strong> · {len(student_rows)} élève(s)"
    meta_right = f"{len(evaluations)} évaluation(s) · établi le {issued_str}"

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="12mm")}
        {_report_styles()}
    </head>
    <body>
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school,
            theme=theme,
            doc_type="RELEVÉ DE NOTES",
            doc_subtitle=subtitle,
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {ui.section_title("Relevé détaillé des notes", theme=theme)}

        {table}

        {stats}

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
