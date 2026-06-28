"""Rapport de synthèse de classe — PDF A4 portrait (conseil de fin de trimestre).

Document interne pour le conseil de classe : palmarès des élèves (rang, moyenne,
mention), statistiques par matière (moyenne de classe, min, max) et indicateurs
clés (effectif, moyenne de classe, taux de réussite). Cadre officiel thémé tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import format_decimal
from app.services.pdf.theme import PDFTheme


def _palmares_rows(palmares: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for entry in palmares:
        rank = entry.get("rank")
        rows.append(
            [
                {"value": str(rank) if rank else "—", "type": "num"},
                {
                    "value": f"<strong>{ui.esc(entry.get('student_name', ''))}</strong>",
                    "type": "html",
                },
                {"value": format_decimal(entry.get("average")), "type": "num"},
                {
                    "value": ui.mention_label(entry["mention"]) if entry.get("mention") else "—",
                    "type": "muted",
                },
            ]
        )
    return rows


def _subject_rows(subjects: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for s in subjects:
        name_cell = f"<strong>{ui.esc(s.get('subject_name', ''))}</strong>"
        teacher = s.get("teacher_name")
        if teacher:
            name_cell += (
                f"<br/><span style='font-size:8px;color:var(--muted);'>{ui.esc(teacher)}</span>"
            )
        rows.append(
            [
                {"value": name_cell, "type": "html"},
                {"value": format_decimal(s.get("class_avg")), "type": "num"},
                {"value": format_decimal(s.get("min")), "type": "muted"},
                {"value": format_decimal(s.get("max")), "type": "muted"},
            ]
        )
    return rows


def generate_class_synthesis_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère le rapport de synthèse de classe en PDF — theme école dynamique."""
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    class_name = data.get("class_name", "") or ""
    level_name = data.get("level_name", "") or ""
    trimester = data.get("trimester", "")
    academic_year = data.get("academic_year_name", "") or ""
    counts = data.get("counts", {}) or {}
    class_stats = data.get("class_stats", {}) or {}
    palmares = data.get("palmares", []) or []
    subjects = data.get("subjects", []) or []
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y") if isinstance(issued_at, datetime) else ""

    total = counts.get("total", 0) or 0
    passed = counts.get("passed", 0) or 0
    success_rate = round(100 * passed / total) if total else 0

    meta_left = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)}<br/>"
        f"<strong>Niveau :</strong> {ui.esc(level_name)}"
    )
    meta_right = f"<span style='color:var(--muted);'>Édité le {ui.esc(issued_str)}</span>"

    kpis = ui.kpis_row(
        cards=[
            {"label": "Effectif", "value": str(total), "tone": "primary"},
            {
                "label": "Moyenne de classe",
                "value": f"{format_decimal(class_stats.get('class_avg'))} / 20",
                "tone": "accent",
            },
            {"label": "Taux de réussite", "value": f"{success_rate} %", "tone": "success"},
        ],
        theme=theme,
    )

    palmares_table = ui.premium_table(
        headers=[
            {"label": "Rang", "align": "right"},
            "Nom et Prénoms",
            {"label": "Moyenne / 20", "align": "right"},
            "Mention",
        ],
        rows=_palmares_rows(palmares),
        theme=theme,
        empty_message="Aucun bulletin pour ce trimestre.",
    )

    subjects_table = ui.premium_table(
        headers=[
            "Matière",
            {"label": "Moy. classe", "align": "right"},
            {"label": "Min", "align": "right"},
            {"label": "Max", "align": "right"},
        ],
        rows=_subject_rows(subjects),
        theme=theme,
        empty_message="Aucune matière notée.",
    )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Professeur Principal"},
            {"role": "Le Chef d'Établissement"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="14mm")}</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="RAPPORT DE SYNTHÈSE",
            doc_subtitle=f"{class_name} — Trimestre {trimester}",
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {kpis}

        {ui.section_title("Palmarès du trimestre", theme=theme)}
        {palmares_table}

        {ui.section_title("Statistiques par matière", theme=theme)}
        {subjects_table}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document interne — conseil de classe de fin de trimestre.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
