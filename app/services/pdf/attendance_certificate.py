"""Attestation de fréquentation officielle — PDF premium signé chef d'établissement.

Document officiel attestant le taux de fréquentation d'un élève (présent,
retard, absence excusée, absence non excusée) sur une période donnée.
Texte officiel grammaticalement adapté au genre.

Refactor 2026-05-18 : utilise `components.py` (header premium, kpis_row
stats, signature_block, footer) + `PDFTheme.from_school`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc
from app.services.pdf.theme import PDFTheme


def _body_paragraph(
    *,
    signatory_html: str,
    full_name: str,
    matricule: str,
    inscrit_form: str,
    class_name: str,
    academic_year_name: str,
    issued_str: str,
    rate: float,
    total: int,
) -> str:
    """Compose le corps officiel de l'attestation."""
    return (
        f"<p>{signatory_html}, atteste que :</p>"
        f"<p style='text-align:center; font-size:15px; margin:18px 0; "
        f"font-family:var(--font-serif,Georgia,serif); color:var(--primary);'>"
        f"<strong>{esc(full_name)}</strong></p>"
        f"<p>matricule <strong>{esc(matricule)}</strong>, est régulièrement "
        f"{esc(inscrit_form)} en classe de <strong>{esc(class_name)}</strong> "
        f"au titre de l'année scolaire <strong>{esc(academic_year_name)}</strong>.</p>"
        f"<p>Au {esc(issued_str)}, son taux de fréquentation s'élève à "
        f"<strong>{rate:.2f}%</strong> sur <strong>{total}</strong> "
        f"séance(s) enregistrée(s).</p>"
    )


def generate_attendance_certificate_pdf(
    data: dict[str, Any], school_settings: dict[str, Any]
) -> bytes:
    """Generate the official attestation de frequentation PDF — theme dynamique.

    data keys :
        student: dict with first_name, last_name, genre, enrollment_number
        class_name: str
        academic_year_name: str
        attendance: dict with total, present, absent, late, excused, attendance_rate
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)

    student = data.get("student", {}) or {}
    first_name = student.get("first_name", "") or ""
    last_name = student.get("last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()
    genre = student.get("genre")
    matricule = student.get("enrollment_number") or "..."

    class_name = data.get("class_name") or ""
    academic_year_name = data.get("academic_year_name") or ""
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y") if isinstance(issued_at, datetime) else ""

    inscrit_form = "inscrite" if genre == "F" else "inscrit"

    attendance = data.get("attendance", {}) or {}
    total = int(attendance.get("total", 0) or 0)
    present = int(attendance.get("present", 0) or 0)
    late = int(attendance.get("late", 0) or 0)
    absent = int(attendance.get("absent", 0) or 0)
    excused = int(attendance.get("excused", 0) or 0)
    rate = float(attendance.get("attendance_rate", 0.0) or 0.0)

    head_master_name = school_settings.get("head_master_name") or "Le Chef d'Établissement"
    head_master_title = school_settings.get("head_master_title") or "Le Chef d'Établissement"
    name_distinct = bool(head_master_name.strip()) and head_master_name != head_master_title

    body_html = _body_paragraph(
        signatory_html=ui.signatory_clause(head_master_name, head_master_title),
        full_name=full_name,
        matricule=matricule,
        inscrit_form=inscrit_form,
        class_name=class_name,
        academic_year_name=academic_year_name,
        issued_str=issued_str,
        rate=rate,
        total=total,
    )

    kpis = ui.kpis_row(
        cards=[
            {"label": "Présent", "value": str(present), "tone": "success"},
            {"label": "Retard", "value": str(late), "tone": "warn"},
            {"label": "Excusée", "value": str(excused), "tone": "accent"},
            {"label": "Non excusée", "value": str(absent), "tone": "primary"},
        ],
        theme=theme,
    )

    ref_year = issued_at.year if isinstance(issued_at, datetime) else datetime.utcnow().year
    reference = (
        f"AF-{ref_year}-{matricule}" if matricule and matricule != "..." else f"AF-{ref_year}"
    )

    school_name = school_settings.get("school_name") or ""
    acro_words = [w for w in school_name.split() if w and w[0].isalpha()]
    acronym = "".join(w[0] for w in acro_words[:4]).upper() or "CACHET"

    serif_style = f"""
    <style>
        :root {{ --font-serif: {theme.font_serif}; }}
        .pdf-cert-title {{
            text-align:center; font-family: var(--font-serif);
            font-size: 21px; letter-spacing: 4px; color: var(--primary);
            margin: 18px 0 6px;
        }}
        .pdf-cert-rule {{
            width: 120px; height: 2px; background: var(--accent);
            margin: 0 auto 4px; border: 0;
        }}
        .pdf-cert-body {{
            line-height: 1.9; font-size: 12.5px; margin: 22px 6mm 0;
            font-family: var(--font-serif); color: var(--ink); text-align: justify;
        }}
        .pdf-cert-date {{
            text-align:right; font-style:italic; font-size: 11px;
            margin: 0 0 4px; color: var(--muted);
        }}
        .pdf-cert-seal-caption {{
            text-align:center; font-size: 8px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px;
        }}
    </style>
    """

    signatures = ui.signature_block(
        roles=[
            {"role": head_master_title, "name": head_master_name if name_distinct else ""},
        ],
        theme=theme,
    )

    header_html = ui.premium_header(school_settings, theme=theme, show_ci_banner=True)

    body_region = f"""
        <h1 class="pdf-cert-title">ATTESTATION DE FRÉQUENTATION</h1>
        <hr class="pdf-cert-rule" />
        <div class="pdf-cert-body">{body_html}</div>
        <div style="margin: 22px 6mm 0;">
            {ui.section_title("Détail des séances", theme=theme)}
            {kpis}
        </div>
    """

    seal_html = ui.seal_block(theme=theme, label=acronym)
    bottom_html = f"""
        <div class="pdf-cert-date">Fait le {esc(issued_str)}</div>
        <div style="display:flex; align-items:flex-end; justify-content:space-between;
                    gap:24px; margin-top:6px;">
            <div style="flex:0 0 auto; text-align:center; padding-bottom:8px;">
                {seal_html}
                <div class="pdf-cert-seal-caption">Cachet &amp; signature</div>
            </div>
            <div style="flex:0 0 320px; max-width:340px;">{signatures}</div>
        </div>
        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            reference=reference,
            note="Document officiel — toute falsification est passible de poursuites.",
        )
    }
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4", margin="14mm")}
        {serif_style}
    </head>
    <body>
        {
        ui.document_frame(
            theme=theme,
            header_html=header_html,
            body_html=body_region,
            bottom_html=bottom_html,
            watermark_text=school_name,
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
