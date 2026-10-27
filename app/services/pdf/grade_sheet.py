"""Feuille de notes — PDF A4 portrait ou paysage vierge à remplir à la main.

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
from typing import Any, Literal

from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

_DEFAULT_NOTE_COLUMNS = 6


def _student_name(student: dict[str, Any]) -> str:
    last = ui.esc(student.get("last_name", ""))
    first = ui.esc(student.get("first_name", ""))
    return f"<strong>{last}</strong> {first}".strip()


def _sheet_styles(orientation: Literal["portrait", "landscape"]) -> str:
    """Cases lisibles et assez hautes pour inscrire les notes au stylo."""
    font_size = "9px" if orientation == "portrait" else "9.5px"
    cell_padding = "3px" if orientation == "portrait" else "5px"
    return f"""
    <style>
        .sheet-table {{ font-size: {font_size}; }}
        .sheet-table thead th {{
            text-align: center; padding-left: {cell_padding};
            padding-right: {cell_padding};
        }}
        .sheet-table thead th.col-name {{ text-align: left; }}
        .sheet-table thead th.col-moy {{ border-bottom-color: var(--accent); }}
        .sheet-table tbody td {{
            height: 26px; padding: 8px {cell_padding};
            vertical-align: middle;
            overflow-wrap: break-word;
        }}
        .sheet-table td.cell-num {{ text-align: center; color: var(--muted); }}
        .sheet-table td.cell-mat {{ text-align: center; font-family: 'Courier New', monospace; }}
        .sheet-table td.cell-blank {{ text-align: center; }}
        .sheet-table td.cell-moy {{ text-align: center; background: var(--soft-bg); }}
        .sheet-table thead th.cell-blank,
        .sheet-table td.cell-blank {{
            border-left: 0.75px solid var(--border);
        }}
        .sheet-table tbody td {{ border-bottom: 0.75px solid var(--border); }}
        .sheet-table tbody tr {{ break-inside: avoid; }}
    </style>
    """


def _colgroup(note_columns: int, orientation: Literal["portrait", "landscape"]) -> str:
    # Les noms gardent de la place, même sur l'A4 étroit en portrait.
    if orientation == "portrait":
        widths = (5, 13, 28, 10)
    else:
        widths = (4, 12, 26, 10)
    num, matricule, name, average = widths
    fixed = [
        f'<col style="width:{num}%">',
        f'<col style="width:{matricule}%">',
        f'<col style="width:{name}%">',
    ]
    note_width = (100 - sum(widths)) / note_columns
    notes = f'<col style="width:{note_width:.3f}%">' * note_columns
    moy = f'<col style="width:{average}%">'
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
    orientation: Literal["portrait", "landscape"] = "landscape",
) -> bytes:
    """Génère la feuille de notes vierge (A4 portrait ou paysage) — thème école.

    `class_info` : {class_name, level_name, academic_year_name, effectif}
    `students` : [{enrollment_number, first_name, last_name}]
    `note_columns` : nombre de colonnes de notes vides (défaut 6).
    `subject_name` / `trimester` : pré-remplissent l'en-tête si fournis,
        sinon des lignes vides à compléter à la main.
    """
    from weasyprint import HTML  # lazy import — GTK requis au runtime

    theme = PDFTheme.from_school(school)
    if orientation not in ("portrait", "landscape"):
        raise ValueError("Orientation de feuille de notes invalide")
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
    meta_right = f"Matière : {subject_label} &nbsp;·&nbsp; {trimester_label}"

    table = (
        '<table class="pdf-table sheet-table">'
        f"{_colgroup(note_columns, orientation)}{_thead(note_columns)}{_tbody(students, note_columns)}"
        "</table>"
    )

    issued_str = datetime.utcnow().strftime("%d/%m/%Y")
    page_css = ui.base_styles(
        theme,
        page_size=f"A4 {orientation}",
        margin="10mm" if orientation == "portrait" else "12mm",
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        {page_css}
        {_sheet_styles(orientation)}
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
