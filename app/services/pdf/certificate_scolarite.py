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
    signatory_html: str,
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
        f"<p>{signatory_html}, certifie que :</p>"
        f"<p style='text-align:center; font-size:15px; margin:18px 0; "
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


def _school_acronym(school_name: str) -> str:
    """Acronyme court de l'école pour le cachet (max 4 lettres)."""
    words = [w for w in (school_name or "").split() if w[0].isalpha()]
    acro = "".join(w[0] for w in words[:4]).upper()
    return acro or "CACHET"


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
    name_distinct = bool(head_master_name.strip()) and head_master_name != head_master_title

    body_html = _body_paragraph(
        signatory_html=ui.signatory_clause(head_master_name, head_master_title),
        full_name=full_name,
        ne_form=ne_form,
        birth_date_str=birth_date_str,
        birthplace=birthplace,
        matricule=matricule,
        inscrit_form=inscrit_form,
        class_name=class_name,
        academic_year_name=academic_year_name,
    )

    # Numéro de référence officialisant (déterministe, sans table — un vrai
    # jeton d'émission + QR arriveront en Phase 5).
    ref_year = issued_at.year if isinstance(issued_at, datetime) else datetime.utcnow().year
    reference = f"CS-{ref_year}-{matricule}" if matricule and matricule != "..." else f"CS-{ref_year}"

    school_name = school_settings.get("school_name") or ""

    # Style serif officiel pour le body officiel
    serif_style = f"""
    <style>
        :root {{ --font-serif: {theme.font_serif}; }}
        .pdf-cert-title {{
            text-align:center; font-family: var(--font-serif);
            font-size: 23px; letter-spacing: 5px; color: var(--primary);
            margin: 18px 0 6px;
        }}
        .pdf-cert-rule {{
            width: 120px; height: 2px; background: var(--accent);
            margin: 0 auto 4px; border: 0;
        }}
        .pdf-cert-body {{
            line-height: 1.9; font-size: 12.5px; margin: 24px 6mm 0;
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
        <h1 class="pdf-cert-title">CERTIFICAT DE SCOLARITÉ</h1>
        <hr class="pdf-cert-rule" />
        <div class="pdf-cert-body">{body_html}</div>
    """

    seal_html = ui.seal_block(theme=theme, label=_school_acronym(school_name))
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
