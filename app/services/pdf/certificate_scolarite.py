"""Certificat de scolarité officiel — PDF République Côte d'Ivoire signé.

Document officiel attestant qu'un élève est régulièrement inscrit dans
l'établissement pour une année scolaire donnée. Signé par le chef
d'établissement. Texte officiel grammaticalement adapté au genre (M/F).

Refactor 2026-05-18 : utilise `components.py` (header premium banner RCI +
serif title + signature_block + footer) + `PDFTheme.from_school`.
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
    ne_form: str,
    birth_date_str: str,
    birthplace: str,
    matricule: str,
    inscrit_form: str,
    class_name: str,
    academic_year_name: str,
) -> str:
    """Compose le corps officiel du certificat (texte grammaticalement correct)."""
    return (
        f"<p>Je soussigné(e), <strong>{esc(head_master_name)}</strong>, "
        f"{esc(head_master_title)}, certifie que :</p>"
        f"<p style='text-align:center; font-size:14px; margin:16px 0; "
        f"font-family:var(--font-serif,Georgia,serif); color:var(--primary);'>"
        f"<strong>{esc(full_name)}</strong></p>"
        f"<p>{esc(ne_form)} le <strong>{esc(birth_date_str)}</strong> à "
        f"<strong>{esc(birthplace)}</strong>, matricule "
        f"<strong>{esc(matricule)}</strong>, est régulièrement {esc(inscrit_form)} "
        f"en classe de <strong>{esc(class_name)}</strong> au titre de l'année "
        f"scolaire <strong>{esc(academic_year_name)}</strong>.</p>"
        f"<p>En foi de quoi, le présent certificat lui est délivré pour servir "
        f"et valoir ce que de droit.</p>"
    )


def generate_certificate_scolarite_pdf(
    data: dict[str, Any], school_settings: dict[str, Any]
) -> bytes:
    """Generate the official certificat de scolarite PDF — theme école dynamique.

    data keys (from student_documents_service.compose_certificate_data):
        student: dict with first_name, last_name, birth_date, genre,
                 enrollment_number, city, commune
        class_name: str
        academic_year_name: str
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)

    student = data.get("student", {}) or {}
    first_name = student.get("first_name", "") or ""
    last_name = student.get("last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip()
    birth_date = student.get("birth_date")
    birth_date_str = birth_date.strftime("%d/%m/%Y") if birth_date else "..."
    genre = student.get("genre")
    matricule = student.get("enrollment_number") or "..."
    # Lieu de naissance : on n'a pas de champ dédié, on utilise la ville
    birthplace = student.get("city") or student.get("commune") or "..."

    class_name = data.get("class_name") or ""
    academic_year_name = data.get("academic_year_name") or ""
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y") if isinstance(issued_at, datetime) else ""

    ne_form = "née" if genre == "F" else "né"
    inscrit_form = "inscrite" if genre == "F" else "inscrit"

    head_master_name = school_settings.get("head_master_name") or "Le Chef d'Établissement"
    head_master_title = school_settings.get("head_master_title") or "Le Chef d'Établissement"

    body_html = _body_paragraph(
        head_master_name=head_master_name,
        head_master_title=head_master_title,
        full_name=full_name,
        ne_form=ne_form,
        birth_date_str=birth_date_str,
        birthplace=birthplace,
        matricule=matricule,
        inscrit_form=inscrit_form,
        class_name=class_name,
        academic_year_name=academic_year_name,
    )

    # Style serif officiel pour le body officiel
    serif_style = f"""
    <style>
        :root {{ --font-serif: {theme.font_serif}; }}
        .pdf-cert-title {{
            text-align:center; font-family: var(--font-serif);
            font-size: 22px; letter-spacing: 4px; color: var(--primary);
            margin: 22px 0 8px;
        }}
        .pdf-cert-body {{
            line-height: 1.8; font-size: 12px; margin: 16px 0;
            font-family: var(--font-serif); color: var(--ink);
        }}
        .pdf-cert-date {{
            text-align:right; font-style:italic; font-size: 11px;
            margin: 22px 0 8px; color: var(--muted);
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

        <h1 class="pdf-cert-title">CERTIFICAT DE SCOLARITÉ</h1>

        <div class="pdf-cert-body">
            {body_html}
        </div>

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
