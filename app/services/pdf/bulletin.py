"""Bulletin de notes — PDF par élève et par trimestre.

Document académique :
- En-tête établissement + bandeau République CI
- Identité élève + classe + année scolaire
- Tableau des matières (moyenne, coefficient)
- KPIs synthèse : moyenne générale, rang, mention
- Décision du conseil + appréciation prof principal (optionnels)
- Signatures Prof principal / Parent / Chef d'Établissement

Refactor 2026-05-18 : utilise `components.py` + `PDFTheme.from_school`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import format_decimal
from app.services.pdf.theme import PDFTheme


def _subject_rows(subject_averages: list[dict[str, Any]]) -> list[list[Any]]:
    """Rows : Matière / Moyenne / Coefficient / Moy. coef. / Appréciation."""
    rows: list[list[Any]] = []
    for sa in subject_averages:
        subject_name = sa.get("subject_name", "")
        raw_avg = sa.get("average")
        avg = format_decimal(raw_avg)
        coef = sa.get("coefficient", 1) or 1
        weighted = format_decimal(float(raw_avg) * coef) if raw_avg is not None else "—"
        rows.append(
            [
                subject_name,
                {"value": avg, "type": "num"},
                {"value": str(coef), "type": "num"},
                {"value": weighted, "type": "num"},
                {"value": ui.appreciation_label(raw_avg), "type": "muted"},
            ]
        )
    return rows


def generate_bulletin_pdf(bulletin_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Generate a PDF bulletin for a single student.

    bulletin_data keys:
        student_name, class_name, trimester, academic_year_name,
        average, rank, total_students, mention, council_decision,
        teacher_comment, subject_averages (list of dicts with
        subject_name, average, coefficient), generated_at
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    student_name = bulletin_data.get("student_name", "")
    class_name = bulletin_data.get("class_name", "")
    trimester = bulletin_data.get("trimester", "")
    academic_year = bulletin_data.get("academic_year_name", "")
    average = format_decimal(bulletin_data.get("average"))
    rank = bulletin_data.get("rank")
    total_students = bulletin_data.get("total_students", 0)
    mention = bulletin_data.get("mention", "")
    council_decision = bulletin_data.get("council_decision", "")
    teacher_comment = bulletin_data.get("teacher_comment", "")
    subject_averages = bulletin_data.get("subject_averages", []) or []
    generated_at = bulletin_data.get("generated_at")

    rank_display = f"{rank}/{total_students}" if rank else "—"
    gen_date = generated_at.strftime("%d/%m/%Y") if isinstance(generated_at, datetime) else ""

    meta_left = (
        f"<strong>Élève :</strong> {ui.esc(student_name)}<br/>"
        f"<strong>Classe :</strong> {ui.esc(class_name)}"
    )
    meta_right = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)}<br/>"
        f"<strong>Date :</strong> {ui.esc(gen_date)}"
    )

    table_section = ui.premium_table(
        headers=[
            "Matière",
            {"label": "Moyenne / 20", "align": "right"},
            {"label": "Coef.", "align": "right"},
            {"label": "Moy. coef.", "align": "right"},
            "Appréciation",
        ],
        rows=_subject_rows(subject_averages),
        theme=theme,
        empty_message="Aucune note saisie pour ce trimestre.",
    )

    kpis = ui.kpis_row(
        cards=[
            {"label": "Moyenne générale", "value": f"{average} / 20", "tone": "primary"},
            {"label": "Rang", "value": rank_display, "tone": "accent"},
            {
                "label": "Mention",
                "value": ui.mention_label(mention) if mention else "—",
                "tone": "success",
            },
        ],
        theme=theme,
    )

    decision_block = ""
    if council_decision:
        decision_block = (
            f'<div style="margin:12px 0; padding:8px 12px; '
            f'border-left:3px solid var(--primary); background:var(--soft-bg); font-size:11px;">'
            f"<strong>Décision du conseil :</strong> {ui.esc(council_decision)}"
            f"</div>"
        )

    comment_block = ""
    if teacher_comment:
        comment_block = (
            ui.section_title("Appréciation du professeur principal", theme=theme)
            + f'<div style="padding:8px 12px; border:1px solid var(--border); '
            f"border-radius:6px; background:var(--soft-bg); font-size:11px; "
            f'line-height:1.5;">{ui.esc(teacher_comment)}</div>'
        )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Professeur Principal"},
            {"role": "Le Parent / Tuteur"},
            {"role": "Le Chef d'Établissement"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="15mm")}</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type=f"BULLETIN — TRIMESTRE {trimester}",
            doc_subtitle=f"{class_name} — {academic_year}" if class_name else None,
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {table_section}

        {kpis}

        {decision_block}

        {comment_block}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document officiel — à conserver précieusement.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
