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
    head_master_name: str,
    head_master_title: str,
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
        f"<p>Je soussigné(e), <strong>{esc(head_master_name)}</strong>, "
        f"{esc(head_master_title)}, atteste que :</p>"
        f"<p style='text-align:center; font-size:14px; margin:16px 0; "
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
    issued_str = (
        issued_at.strftime("%d/%m/%Y") if isinstance(issued_at, datetime) else ""
    )

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

    body_html = _body_paragraph(
        head_master_name=head_master_name,
        head_master_title=head_master_title,
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

    serif_style = f"""
    <style>
        :root {{ --font-serif: {theme.font_serif}; }}
        .pdf-cert-title {{
            text-align:center; font-family: var(--font-serif);
            font-size: 20px; letter-spacing: 3px; color: var(--primary);
            margin: 18px 0 8px;
        }}
        .pdf-cert-body {{
            line-height: 1.7; font-size: 12px; margin: 14px 0;
            font-family: var(--font-serif); color: var(--ink);
        }}
        .pdf-cert-date {{
            text-align:right; font-style:italic; font-size: 11px;
            margin: 18px 0 8px; color: var(--muted);
        }}
    </style>
    """

    signatures = ui.signature_block(
        roles=[
            {"role": head_master_title, "name": head_master_name},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
        {ui.base_styles(theme, page_size='A4', margin='18mm')}
        {serif_style}
    </head>
    <body>
        {ui.premium_header(
            school_settings,
            theme=theme,
            show_ci_banner=True,
        )}

        <h1 class="pdf-cert-title">ATTESTATION DE FRÉQUENTATION</h1>

        <div class="pdf-cert-body">
            {body_html}
        </div>

        {ui.section_title("Détail des séances", theme=theme)}
        {kpis}

        <div class="pdf-cert-date">
            Fait le {esc(issued_str)}
        </div>

        {signatures}

        {ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document officiel — toute falsification est passible de poursuites.",
        )}
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
