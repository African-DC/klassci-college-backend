"""Feuille de notes — PDF A4 paysage vierge à remplir à la main.

Feuille de travail imprimable pour reporter les notes au stylo : masthead
sobre, titre, puis un tableau dont les colonnes de notes (Note 1..K) et la
colonne Moyenne sont vides, prêtes à être remplies à la main.

Ce n'est PAS un document officiel vérifiable : pas de Cachet Électronique
Visible, pas de signature élève, juste l'en-tête institutionnel + le tableau.

Persona : l'enseignant imprime cette feuille pour saisir les notes d'une
matière sur un trimestre avant de les reporter dans le système.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

_DEFAULT_NOTE_COLUMNS = 6


def _student_name(student: dict[str, Any]) -> str:
    last = ui.esc(student.get("last_name", ""))
    first = ui.esc(student.get("first_name", ""))
    return f"<strong>{last}</strong> {first}".strip()


def _sheet_styles() -> str:
    """Styles complémentaires : colonnes de notes + moyenne + lignes hautes."""
    return """
    <style>
        .sheet-table { font-size: 9.5px; }
        .sheet-table thead th { text-align: center; }
        .sheet-table thead th.col-name { text-align: left; }
        .sheet-table thead th.col-moy { border-bottom-color: var(--accent); }
        .sheet-table tbody td {
            height: 24px; padding-top: 9px; padding-bottom: 9px;
            vertical-align: middle;
        }
        .sheet-table td.cell-num { text-align: center; color: var(--muted); }
        .sheet-table td.cell-mat { text-align: center; font-family: 'Courier New', monospace; }
        .sheet-table td.cell-blank { text-align: center; }
        .sheet-table td.cell-moy { text-align: center; background: var(--soft-bg); }
    </style>
    """


def _colgroup(note_columns: int) -> str:
    fixed = ['<col style="width:4%">', '<col style="width:12%">', '<col style="width:26%">']
    remaining = 100 - 42 - 10  # 10% pour la colonne Moyenne
    note_width = remaining / note_columns
    notes = f'<col style="width:{note_width:.3f}%">' * note_columns
    moy = '<col style="width:10%">'
    return f"<colgroup>{''.join(fixed)}{notes}{moy}</colgroup>"


def _thead(note_columns: int) -> str:
    note_cells = "".join(f"<th>Note {i}</th>" for i in range(1, note_columns + 1))
    return (
        "<thead><tr>"
        '<th>N°</th><th>Matricule</th><th class="col-name">Nom et prénoms</th>'
        f"{note_cells}"
        '<th class="col-moy">Moyenne</th>'
        "</tr></thead>"
    )


def _tbody(students: list[dict[str, Any]], note_columns: int) -> str:
    if not students:
        span = note_columns + 4
        return (
            "<tbody><tr>"
            f'<td colspan="{span}" style="text-align:center; color:var(--muted); padding:16px;">'
            "Aucun élève inscrit dans cette classe pour l'année courante."
            "</td></tr></tbody>"
        )
    note_cells = '<td class="cell-blank">&nbsp;</td>' * note_columns
    rows: list[str] = []
    for i, s in enumerate(students, 1):
        matricule = ui.esc(str(s.get("enrollment_number") or "—"))
        rows.append(
            "<tr>"
            f'<td class="cell-num">{i}</td>'
            f'<td class="cell-mat">{matricule}</td>'
            f"<td>{_student_name(s)}</td>"
            f"{note_cells}"
            '<td class="cell-moy">&nbsp;</td>'
            "</tr>"
        )
    return f"<tbody>{''.join(rows)}</tbody>"


def generate_grade_sheet_pdf(
    school: dict[str, Any],
    class_info: dict[str, Any],
    students: list[dict[str, Any]],
    note_columns: int = _DEFAULT_NOTE_COLUMNS,
    subject_name: str = "",
    trimester: int | None = None,
) -> bytes:
    """Génère la feuille de notes vierge (paysage A4) — theme école dynamique.

    `class_info` : {class_name, level_name, academic_year_name, effectif}
    `students` : [{enrollment_number, first_name, last_name}]
    `note_columns` : nombre de colonnes de notes vides (défaut 6).
    `subject_name` / `trimester` : pré-remplissent l'en-tête si fournis,
        sinon des lignes vides à compléter à la main.
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)
    note_columns = max(1, note_columns)

    class_name = class_info.get("class_name", "") or ""
    level_name = class_info.get("level_name", "") or ""
    academic_year = class_info.get("academic_year_name", "") or ""
    effectif = class_info.get("effectif", len(students))

    subtitle = f"{class_name} — {level_name}" if level_name else class_name

    meta_left = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)} &nbsp;·&nbsp; "
        f"<strong>Effectif :</strong> {effectif}"
    )
    subject_label = ui.esc(subject_name) if subject_name else "_______________"
    trimester_label = f"Trimestre {trimester}" if trimester else "_______________"
    meta_right = f"Matière : {subject_label} &nbsp;·&nbsp; Trimestre : {trimester_label}"

    table = (
        '<table class="pdf-table sheet-table">'
        f"{_colgroup(note_columns)}{_thead(note_columns)}{_tbody(students, note_columns)}"
        "</table>"
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
            doc_type="FEUILLE DE NOTES",
            doc_subtitle=subtitle,
        )
    }
        <div class="pdf-meta-strip">
            <div>{meta_left}</div>
            <div style="text-align:right; color:var(--muted);">{meta_right}</div>
        </div>

        {table}

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
