"""Liste de classe — PDF A4 portrait premium (conseil, sortie scolaire, appel).

Tableau premium par classe :
- N° matricule, Nom Prénom, Genre, Date de naissance
- Téléphone parent urgence
- Photo miniature (ou initiales fallback)
- Pied de page : signatures Professeur principal / Chef d'Établissement

Persona : Mme Diallo imprime ce document avant chaque conseil de classe
ou sortie scolaire. Format A4 portrait, dense lisible.

Refactor 2026-05-18 : utilise `components.py` (header premium, meta_banner,
kpis_row, premium_table avec cells html photo, signature_block, footer) +
`PDFTheme.from_school`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._class_roster_parts import (
    counter_kpis,
    student_rows,
)
from app.services.pdf.theme import PDFTheme


def generate_class_roster_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère la liste de classe en PDF — theme école dynamique.

    data keys (composé par class_roster_service) :
        class_name: str
        level_name: str (ex: "6ème")
        academic_year_name: str
        main_teacher_name: str | None
        room_name: str | None
        students: list[{
            enrollment_number, first_name, last_name, genre, birth_date,
            initials, photo_url, parent_phone
        }]
        counts: {total, boys, girls}
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)

    class_name = data.get("class_name", "") or ""
    level_name = data.get("level_name", "") or ""
    academic_year = data.get("academic_year_name", "") or ""
    main_teacher = data.get("main_teacher_name") or "—"
    room_name = data.get("room_name") or "—"
    students = data.get("students", []) or []
    counts = data.get("counts", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y %H:%M")

    meta_left = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)}<br/>"
        f"<strong>Salle :</strong> {ui.esc(room_name)}"
    )
    meta_right = (
        f"<strong>Prof. principal :</strong> {ui.esc(main_teacher)}<br/>"
        f"<span style='color:var(--muted);'>Édité le {ui.esc(issued_str)}</span>"
    )

    kpis = ui.kpis_row(cards=counter_kpis(counts), theme=theme)

    table_section = ui.premium_table(
        headers=[
            {"label": "N°", "align": "right"},
            "Photo",
            "Matricule",
            "Nom et Prénoms",
            {"label": "Sexe", "align": "center"},
            "Né(e) le",
            "Tél. parent urgence",
        ],
        rows=student_rows(students),
        theme=theme,
        empty_message="Aucun élève inscrit dans cette classe pour l'année courante.",
    )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Professeur Principal", "name": main_teacher},
            {"role": "Le Chef d'Établissement"},
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
            doc_type="LISTE DE CLASSE",
            doc_subtitle=f"{class_name} — {level_name}",
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {kpis}

        {table_section}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document confidentiel — pour usage interne (conseil de classe, sortie scolaire, appel).",
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
