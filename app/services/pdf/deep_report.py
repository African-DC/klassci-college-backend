"""Rapport de fin de trimestre DEEP — PDF A4 paysage multi-pages.

Le canevas officiel enchaîne 27 tableaux, dont certains à plus de trente
colonnes : le paysage n'est pas un choix esthétique, c'est la seule
orientation où les grilles tiennent sans rogner un chiffre.

Le document reste habillé du gabarit premium de l'établissement (couleurs,
logo, en-tête et pied officiels), comme les autres pièces que l'école dépose
à l'administration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.deep_report._types import DeepReport
from app.services.pdf import _deep_report_parts as parts
from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme


def generate_deep_report_pdf(report: DeepReport, school: dict[str, Any]) -> bytes:
    """Génère le rapport DEEP complet — thème école dynamique."""
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)
    issued_on = datetime.now().strftime("%d/%m/%Y")

    chapters_html = "".join(parts.chapter_html(chapter, theme=theme) for chapter in report.chapters)

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="11mm 10mm")}
        {parts.extra_styles()}
    </head>
    <body>
        {
        ui.premium_header(
            school,
            theme=theme,
            doc_type="RAPPORT DE FIN DE TRIMESTRE",
            doc_subtitle=(
                f"Année scolaire {ui.esc(report.academic_year_name)} — trimestre {report.trimester}"
            ),
        )
    }
        {parts.cover_html(school, report, issued_on=issued_on)}
        {chapters_html}
        {_conclusion_html(report)}
        {
        ui.premium_footer(
            school,
            theme=theme,
            note=(
                f"Rapport établi le {ui.esc(issued_on)} — canevas DEEP, "
                "enseignement secondaire général."
            ),
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()


def _conclusion_html(report: DeepReport) -> str:
    """Conclusion, suivie du rappel des tableaux laissés à compléter."""
    pending = report.pending_table_numbers
    pending_block = ""
    if pending:
        numbers = ", ".join(str(number) for number in pending)
        pending_block = (
            "<div class='deep-pending'><strong>Tableaux à compléter manuellement :</strong> "
            f"{ui.esc(numbers)}. Ils appellent des informations que la plateforme ne "
            "collecte pas ; ils sont laissés vierges plutôt que remplis de zéros.</div>"
        )
    return f"""
    <section class="deep-conclusion">
        <div class="deep-chapter-title">Conclusion</div>
        <div class="deep-conclusion-body">{ui.esc(report.conclusion)}</div>
        {pending_block}
    </section>
    """
