"""Fiche d'inscription — PDF officiel à signer par parent + admin.

Document remis au parent à la rentrée :
- Bandeau République CI + entête école (logo, code MENA)
- Métadonnées : N° inscription + statut + niveau + date édition
- Identité élève (photo + sexe + naissance + adresse)
- Responsables légaux (Père / Mère / Tuteur)
- Frais scolaires détaillés avec total
- Signatures Parent / Tuteur + Chef d'Établissement

Persona : Mariam Koné reçoit ce document au secrétariat, le signe,
en garde une copie. Format A4 portrait, dense mais lisible.

Refactor 2026-05-18 : utilise `components.py` + `PDFTheme.from_school`.
Helpers spécifiques fiche extraits dans `_enrollment_form_parts.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._enrollment_form_parts import (
    fee_rows_and_total,
    parents_grid,
    student_identity_block,
)
from app.services.pdf._helpers import enum_value
from app.services.pdf.theme import PDFTheme, status_label


def generate_enrollment_form_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère la fiche d'inscription officielle en PDF.

    data keys (composé par enrollment_form_service) :
        enrollment_id, enrollment_number, status,
        student: {first_name, last_name, genre, birth_date, birthplace,
                  photo_url, city, commune, address},
        class_name, level_name, academic_year_name,
        parents: list[{first_name, last_name, phone, email, relationship_label}],
        fees: list[{category_name, amount, is_mandatory}],
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)

    enrollment_id = data.get("enrollment_id", "")
    enrollment_number = data.get("enrollment_number") or f"#{enrollment_id}"
    class_name = data.get("class_name", "")
    level_name = data.get("level_name", "")
    academic_year = data.get("academic_year_name", "")
    status_key = enum_value(data.get("status", "prospect")) or "prospect"
    status_text = status_label(status_key)

    student = data.get("student", {}) or {}
    parents = data.get("parents", []) or []
    fees = data.get("fees", []) or []
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y %H:%M")

    # Meta banner : N° inscription + statut [pill] à gauche, niveau + édition à droite
    meta_left = (
        f"<strong>N° inscription :</strong> {ui.esc(enrollment_number)}<br/>"
        f"<strong>Statut :</strong> "
        f"{ui.status_pill(status_key, label=status_text)}"
    )
    meta_right = (
        f"<strong>Niveau :</strong> {ui.esc(level_name)}<br/>"
        f'<span class="muted">Édité le {ui.esc(issued_str)}</span>'
    )

    # Frais : rows + total
    fee_rows, total_row = fee_rows_and_total(fees)
    fees_table = ui.premium_table(
        headers=[
            "Catégorie",
            "Type",
            {"label": "Montant XOF", "align": "right"},
        ],
        rows=fee_rows,
        theme=theme,
        empty_message="Aucun frais configuré pour cette inscription.",
        total_row=total_row,
    )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Parent / Tuteur", "subline": 'Signature précédée de "Lu et approuvé"'},
            {"role": "Le Chef d'Établissement", "subline": "Signature et cachet"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="14mm")}</head>
    <body>
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="FICHE D'INSCRIPTION",
            doc_subtitle=f"{class_name} — {academic_year}" if class_name else None,
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {ui.section_title("Identité de l'élève", theme=theme)}
        {student_identity_block(student)}

        {ui.section_title("Responsables légaux", theme=theme)}
        {parents_grid(parents)}

        {ui.section_title("Frais scolaires", theme=theme)}
        {fees_table}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Conserver précieusement — à présenter au secrétariat sur demande.",
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
