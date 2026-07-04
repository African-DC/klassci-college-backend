"""Statistiques DREN — PDF A4 portrait premium.

Restitue les indicateurs attendus par la Direction Régionale de l'Éducation
Nationale (effectifs par niveau et par sexe, taux de réussite, d'échec, de
redoublement et d'exclusion, moyennes par matière), habillés du même design
institutionnel que les autres documents officiels.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme


def _pct(value: float | None) -> str:
    return f"{value:.1f} %" if value is not None else "—"


def _avg(value: Any) -> str:
    return f"{ui.format_decimal(value)} / 20" if value is not None else "—"


def generate_dren_stats_pdf(school: dict[str, Any], data: Any) -> bytes:
    """Génère le PDF des statistiques DREN — theme école dynamique.

    `data` : instance de `DrenStatsResponse` (accès par attributs).
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)

    kpis = [
        {"label": "Effectif total", "value": str(data.total_students), "tone": "accent"},
        {"label": "Taux de réussite", "value": _pct(data.success_rate), "tone": "success"},
        {"label": "Taux d'échec", "value": _pct(data.failure_rate)},
        {"label": "Redoublement", "value": _pct(data.redoublement_rate)},
    ]
    stats_band = ui.kpis_row(kpis, theme=theme)

    meta_left = (
        f"<strong>Garçons / Filles :</strong> {data.male_count} / {data.female_count}"
    )
    meta_right = f"Taux d'exclusion : {_pct(data.exclusion_rate)}"
    meta = ui.meta_banner(meta_left, meta_right, theme=theme)

    # Effectifs par niveau
    level_rows = [
        [
            lvl.level_name,
            {"value": str(lvl.total_students), "type": "num"},
            {"value": str(lvl.male_count), "type": "num"},
            {"value": str(lvl.female_count), "type": "num"},
        ]
        for lvl in data.levels
    ]
    level_total = [
        "Total établissement",
        {"value": str(data.total_students), "type": "num"},
        {"value": str(data.male_count), "type": "num"},
        {"value": str(data.female_count), "type": "num"},
    ]
    levels_table = ui.premium_table(
        [
            "Niveau",
            {"label": "Effectif", "align": "right"},
            {"label": "Garçons", "align": "right"},
            {"label": "Filles", "align": "right"},
        ],
        level_rows,
        theme=theme,
        total_row=level_total,
        empty_message="Aucun niveau renseigné pour cette année.",
        col_widths=["46%", "18%", "18%", "18%"],
    )

    # Détail par classe
    class_rows: list[list[Any]] = []
    for lvl in data.levels:
        for cls in lvl.classes:
            class_rows.append(
                [
                    cls.class_name,
                    lvl.level_name,
                    {"value": str(cls.total_students), "type": "num"},
                    {"value": str(cls.male_count), "type": "num"},
                    {"value": str(cls.female_count), "type": "num"},
                    {"value": _avg(cls.average), "type": "emphasis"},
                ]
            )
    classes_table = ui.premium_table(
        [
            "Classe",
            "Niveau",
            {"label": "Effectif", "align": "right"},
            {"label": "G", "align": "right"},
            {"label": "F", "align": "right"},
            {"label": "Moyenne", "align": "right"},
        ],
        class_rows,
        theme=theme,
        empty_message="Aucune classe renseignée pour cette année.",
        col_widths=["26%", "24%", "14%", "10%", "10%", "16%"],
    )

    # Moyennes par matière
    subject_rows = [
        [
            subj.subject_name,
            {"value": _avg(subj.overall_average), "type": "emphasis"},
            {"value": str(subj.teacher_count), "type": "num"},
        ]
        for subj in data.subjects
    ]
    subjects_table = ui.premium_table(
        [
            "Matière",
            {"label": "Moyenne générale", "align": "right"},
            {"label": "Enseignants", "align": "right"},
        ],
        subject_rows,
        theme=theme,
        empty_message="Aucune moyenne de matière disponible.",
        col_widths=["50%", "30%", "20%"],
    )

    issued_str = datetime.utcnow().strftime("%d/%m/%Y")

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 portrait", margin="14mm")}
    </head>
    <body>
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school,
            theme=theme,
            doc_type="STATISTIQUES DREN",
            doc_subtitle=f"Année scolaire {ui.esc(data.academic_year_name)}",
        )
    }

        {stats_band}

        {meta}

        {ui.section_title("Effectifs par niveau", theme=theme)}
        {levels_table}

        {ui.section_title("Détail par classe", theme=theme)}
        {classes_table}

        {ui.section_title("Moyennes par matière", theme=theme)}
        {subjects_table}

        {
        ui.premium_footer(
            school,
            theme=theme,
            note=(
                f"Statistiques établies le {issued_str} — "
                "indicateurs conformes au suivi DREN / SIGE."
            ),
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
