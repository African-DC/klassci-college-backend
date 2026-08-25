"""Feuille d'appel — PDF A4 paysage vierge à remplir à la main.

Feuille de travail imprimable pour l'appel papier : masthead sobre, titre,
puis un tableau dont les colonnes de présence (numérotées 1..N) sont vides,
prêtes à être cochées au stylo pour chaque jour ou séance.

Ce n'est PAS un document officiel vérifiable : pas de Cachet Électronique
Visible, pas de signature élève, juste l'en-tête institutionnel + le tableau.

Persona : Mme Diallo / l'enseignant impriment cette feuille en début de
période et cochent la présence à la main pendant l'appel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

_DEFAULT_COLUMNS = 25


def _student_name(student: dict[str, Any]) -> str:
    last = ui.esc(student.get("last_name", ""))
    first = ui.esc(student.get("first_name", ""))
    return f"<strong>{last}</strong> {first}".strip()


def _sheet_styles() -> str:
    """Styles complémentaires : colonnes de présence étroites + lignes hautes."""
    return """
    <style>
        .sheet-table {{ font-size: 9.5px; }}
        .sheet-table thead th {{ text-align: center; }}
        .sheet-table thead th.col-name {{ text-align: left; }}
        .sheet-table tbody td {{
            height: 22px; padding-top: 8px; padding-bottom: 8px;
            vertical-align: middle;
        }}
        .sheet-table td.cell-num {{ text-align: center; color: var(--muted); }}
        .sheet-table td.cell-mat {{ text-align: center; font-family: 'Courier New', monospace; }}
        .sheet-table td.cell-blank {{ text-align: center; }}
        /* Une feuille qu'on remplit au stylo a besoin de cases. Sans filet
           vertical, les colonnes n'existaient qu'en en-tete : l'enseignant
           n'avait aucun reperage pour cocher en face du bon eleve, et sur ce
           document la grille EST la fonction. */
        .sheet-table thead th.cell-blank,
        .sheet-table td.cell-blank {{
            border-left: 0.75px solid var(--border);
        }}
        .sheet-table tbody td {{
            border-bottom: 0.75px solid var(--border);
        }}
        .sheet-legend {{
            margin-top: 10px; font-size: 8.5px; color: var(--muted);
            letter-spacing: 0.2px;
        }}
        .sheet-legend strong {{ color: var(--ink); }}
    </style>
    """


def _colgroup(columns: int) -> str:
    fixed = ['<col style="width:4%">', '<col style="width:11%">', '<col style="width:21%">']
    blank_width = (100 - 36) / columns
    blank = f'<col style="width:{blank_width:.3f}%">' * columns
    return f"<colgroup>{''.join(fixed)}{blank}</colgroup>"


def _thead(columns: int) -> str:
    number_cells = "".join(f"<th>{i}</th>" for i in range(1, columns + 1))
    return (
        "<thead><tr>"
        '<th>N°</th><th>Matricule</th><th class="col-name">Nom et prénoms</th>'
        f"{number_cells}"
        "</tr></thead>"
    )


def _tbody(students: list[dict[str, Any]], columns: int) -> str:
    if not students:
        span = columns + 3
        return (
            "<tbody><tr>"
            f'<td colspan="{span}" style="text-align:center; color:var(--muted); padding:16px;">'
            "Aucun élève inscrit dans cette classe pour l'année courante."
            "</td></tr></tbody>"
        )
    blank_cells = '<td class="cell-blank">&nbsp;</td>' * columns
    rows: list[str] = []
    for i, s in enumerate(students, 1):
        matricule = ui.esc(str(s.get("enrollment_number") or "—"))
        rows.append(
            "<tr>"
            f'<td class="cell-num">{i}</td>'
            f'<td class="cell-mat">{matricule}</td>'
            f"<td>{_student_name(s)}</td>"
            f"{blank_cells}"
            "</tr>"
        )
    return f"<tbody>{''.join(rows)}</tbody>"


def generate_attendance_sheet_pdf(
    school: dict[str, Any],
    class_info: dict[str, Any],
    students: list[dict[str, Any]],
    columns: int = _DEFAULT_COLUMNS,
) -> bytes:
    """Génère la feuille d'appel vierge (paysage A4) — theme école dynamique.

    `class_info` : {class_name, level_name, academic_year_name, effectif}
    `students` : [{enrollment_number, first_name, last_name}]
    `columns` : nombre de colonnes de présence vides (défaut 25).
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)
    columns = max(1, columns)

    class_name = class_info.get("class_name", "") or ""
    level_name = class_info.get("level_name", "") or ""
    academic_year = class_info.get("academic_year_name", "") or ""
    effectif = class_info.get("effectif", len(students))

    subtitle = f"{class_name} — {level_name}" if level_name else class_name

    meta_left = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)} &nbsp;·&nbsp; "
        f"<strong>Effectif :</strong> {effectif}"
    )
    meta_right = "Période : _______________ &nbsp;·&nbsp; Enseignant : _______________"

    table = (
        '<table class="pdf-table sheet-table">'
        f"{_colgroup(columns)}{_thead(columns)}{_tbody(students, columns)}"
        "</table>"
    )

    legend = (
        '<div class="sheet-legend">'
        "<strong>Légende :</strong> P = Présent · A = Absent · R = Retard · E = Excusé"
        "</div>"
    )

    issued_str = datetime.utcnow().strftime("%d/%m/%Y")

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="12mm")}
        {_sheet_styles()}
    </head>
    <body>
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school,
            theme=theme,
            doc_type="FEUILLE D'APPEL",
            doc_subtitle=subtitle,
        )
    }
        <div class="pdf-meta-strip">
            <div>{meta_left}</div>
            <div style="text-align:right; color:var(--muted);">{meta_right}</div>
        </div>

        {table}
        {legend}

        {
        ui.premium_footer(
            school,
            theme=theme,
            note=f"Feuille de travail à remplir à la main — éditée le {issued_str}.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
