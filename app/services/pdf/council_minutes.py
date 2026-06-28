"""PV de conseil de classe — PDF landscape A4 premium.

Document académique trimestriel listant les décisions du conseil de classe
(passage, redoublement, exclusion, repêchage) pour chaque élève. Signé par
le prof principal, le chef d'établissement et le DREN.

Refactor 2026-05-18 : utilise `components.py` (header premium, meta_banner,
premium_table avec pills décisions, kpis_row récap, signature_block) +
`PDFTheme` instancié depuis `school_settings` pour personnalisation tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._council_minutes_parts import (
    decision_rows,
    recap_kpis,
)
from app.services.pdf.theme import PDFTheme


def generate_council_minutes_pdf(
    council_data: dict[str, Any], school_settings: dict[str, Any]
) -> bytes:
    """Generate a landscape A4 PDF for the council minutes (PV).

    council_data keys:
        class_name, trimester, academic_year_name,
        main_teacher_name, director_name, dren_name, notes,
        generated_at, decisions (list of dicts with
        student_name, average, rank, absence_count,
        auto_decision, final_decision, override_reason)

    school_settings keys:
        school_name, ministry_code, address, phone, email, logo_url,
        head_master_name, head_master_title, primary_color, accent_color.
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    class_name = council_data.get("class_name", "") or ""
    trimester = council_data.get("trimester", "") or ""
    academic_year = council_data.get("academic_year_name", "") or ""
    main_teacher = council_data.get("main_teacher_name", "") or "—"
    director = council_data.get("director_name", "") or "—"
    dren = council_data.get("dren_name", "") or "—"
    notes = council_data.get("notes", "") or ""
    generated_at = council_data.get("generated_at")
    decisions = council_data.get("decisions", []) or []

    gen_date = generated_at.strftime("%d/%m/%Y") if isinstance(generated_at, datetime) else ""
    total_students = len(decisions)

    meta_left = (
        f"<strong>Classe :</strong> {ui.esc(class_name)}<br/>"
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)}<br/>"
        f"<strong>Effectif :</strong> {total_students}"
    )
    meta_right = (
        f"<strong>Prof. principal :</strong> {ui.esc(main_teacher)}<br/>"
        f"<strong>Chef d'établissement :</strong> {ui.esc(director)}<br/>"
        f"<strong>DREN :</strong> {ui.esc(dren)}<br/>"
        f"<strong>Date :</strong> {ui.esc(gen_date)}"
    )

    table_section = ui.premium_table(
        headers=[
            {"label": "N°", "align": "center"},
            "Nom et Prénoms",
            {"label": "Moyenne", "align": "right"},
            {"label": "Rang", "align": "right"},
            {"label": "Absences", "align": "right"},
            "Décision auto",
            "Décision finale",
            "Motif modification",
        ],
        rows=decision_rows(decisions),
        theme=theme,
        empty_message="Aucune décision enregistrée pour ce conseil.",
    )

    kpis = ui.kpis_row(cards=recap_kpis(decisions), theme=theme)

    notes_block = ""
    if notes:
        notes_block = (
            ui.section_title("Observations du conseil", theme=theme)
            + f'<div style="padding:8px 12px; border:1px solid var(--border); '
            f"border-radius:6px; background:var(--soft-bg); font-size:10.5px; "
            f'line-height:1.5;">{ui.esc(notes)}</div>'
        )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Professeur Principal", "name": main_teacher},
            {"role": "Le Chef d'Établissement", "name": director},
            {"role": "Le DREN", "name": dren},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{
        ui.base_styles(theme, page_size="A4 landscape", margin="12mm")
    }</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type=f"PROCÈS-VERBAL DU CONSEIL DE CLASSE — TRIMESTRE {trimester}",
            doc_subtitle=class_name if class_name else None,
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {table_section}

        {ui.section_title("Récapitulatif", theme=theme)}
        {kpis}

        {notes_block}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document officiel — à archiver dans le registre des conseils de classe.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
