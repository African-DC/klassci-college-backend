"""Rendu des tableaux du rapport DEEP — en-têtes sur deux niveaux, notes.

`premium_table` couvre l'immense majorité des besoins du produit, mais le
canevas de la DEEP impose des en-têtes à deux étages (« Effectifs réels »
chapeautant F / G / T) et des lignes de total intercalées au fil du tableau,
pas seulement en pied. Ces deux besoins sont propres à ce document : ils
vivent ici plutôt que d'alourdir la primitive partagée.

Exporté via `deep_report.py`. Ne pas importer depuis un autre generator.
"""

from __future__ import annotations

from typing import Any

from app.services.deep_report._types import DeepReport, ReportChapter, ReportTable
from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

# Au-delà d'une quinzaine de colonnes, la taille de police doit tomber pour que
# la grille tienne dans la largeur d'une A4 paysage sans rogner un chiffre.
_DENSE_COLUMN_THRESHOLD = 14


def extra_styles() -> str:
    """Styles propres au rapport : grilles denses, notes, pages de chapitre."""
    return """
    <style>
        .deep-cover { text-align: center; padding-top: 18mm; }
        .deep-cover-ministry {
            font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px;
            line-height: 1.9; color: var(--ink);
        }
        .deep-cover-title {
            font-family: var(--font-display); font-weight: 700; font-size: 22px;
            color: var(--primary); margin: 16mm auto 0; max-width: 210mm;
            line-height: 1.35; text-transform: uppercase;
        }
        .deep-cover-school {
            font-family: var(--font-display); font-size: 16px; font-weight: 700;
            margin-top: 12mm;
        }
        .deep-cover-meta { font-size: 11px; color: var(--muted); margin-top: 4mm; }

        .deep-chapter { page-break-before: always; }
        .deep-chapter-title {
            font-family: var(--font-display); font-weight: 700; font-size: 14px;
            color: var(--primary); text-transform: uppercase; letter-spacing: 0.6px;
            border-bottom: 1.5px solid var(--primary); padding-bottom: 5px;
            margin-bottom: 8px;
        }
        .deep-chapter-intro { font-size: 9.5px; color: var(--muted); margin-bottom: 10px; }

        .deep-block { margin: 0 0 12px; page-break-inside: auto; }
        .deep-caption {
            font-size: 10px; font-weight: 600; color: var(--primary);
            text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 4px;
        }
        .deep-caption-sub {
            font-size: 9.5px; font-weight: 400; color: var(--muted);
            text-transform: none; letter-spacing: 0;
        }
        .deep-flag {
            display: inline-block; margin-left: 8px; padding: 1px 7px;
            border-radius: 999px; background: var(--soft-bg); color: var(--accent);
            border: 0.75px solid var(--accent);
            font-size: 7.5px; font-weight: 700; letter-spacing: 0.3px;
        }
        .deep-note {
            font-size: 8.5px; color: var(--muted); font-style: italic;
            margin-top: 4px; line-height: 1.5;
        }
        .deep-empty {
            font-size: 9px; color: var(--muted); text-align: center;
            padding: 10px 8px; border: 0.75px dashed var(--border); border-radius: 4px;
        }

        table.deep-table { table-layout: auto; }
        table.deep-table thead { display: table-header-group; }
        table.deep-table thead th {
            padding: 4px 5px; font-size: 7.5px; text-align: center;
            border-right: 0.5px solid var(--border);
        }
        table.deep-table thead th.is-left { text-align: left; }
        table.deep-table tbody td {
            padding: 3px 5px; border-right: 0.5px solid var(--border);
            vertical-align: middle;
        }
        table.deep-table tbody td.is-center {
            text-align: center; font-variant-numeric: tabular-nums;
        }
        table.deep-table tbody td.is-right {
            text-align: right; font-variant-numeric: tabular-nums;
        }
        table.deep-table.is-dense { font-size: 7.5px; }
        table.deep-table.is-dense tbody td { padding: 2px 3px; }
        table.deep-table.is-dense thead th { padding: 3px 3px; font-size: 7px; }
        table.deep-table tbody tr.total-row td {
            background: var(--soft-bg); border-top: 1px solid var(--accent);
            border-bottom: 0.75px solid var(--border);
            font-weight: 700; color: var(--primary);
        }

        .deep-conclusion { page-break-before: always; }
        .deep-conclusion-body { font-size: 10px; line-height: 1.7; margin-top: 6px; }
        .deep-pending {
            margin-top: 8px; padding: 8px 10px; font-size: 9px;
            border-left: 3px solid var(--accent); background: var(--soft-bg);
        }
    </style>
    """


def cover_html(school: dict[str, Any], report: DeepReport, *, issued_on: str) -> str:
    """Page de garde reprenant l'en-tête officiel du canevas."""
    school_name = ui.esc(school.get("school_name") or "Établissement")
    ministry_code = school.get("ministry_code")
    code_line = (
        f"<div class='deep-cover-meta'>Code établissement : {ui.esc(ministry_code)}</div>"
        if ministry_code
        else ""
    )
    return f"""
    <div class="deep-cover">
        <div class="deep-cover-ministry">
            Ministère de l'Éducation nationale et de l'Alphabétisation<br/>
            Direction régionale de l'Éducation nationale de Bouaké 2<br/>
            DEEP — Direction de l'Encadrement des Établissements Privés
        </div>
        <div class="deep-cover-title">
            Présentation du rapport de fin de {ui.esc(_ordinal(report.trimester))} trimestre
            <br/>(Enseignement secondaire général)
        </div>
        <div class="deep-cover-school">{school_name}</div>
        <div class="deep-cover-meta">
            Année scolaire {ui.esc(report.academic_year_name)}
        </div>
        {code_line}
        <div class="deep-cover-meta">Établi le {ui.esc(issued_on)}</div>
    </div>
    """


def chapter_html(chapter: ReportChapter, *, theme: PDFTheme) -> str:
    """Un chapitre : titre, introduction éventuelle, puis ses tableaux."""
    intro = (
        f"<div class='deep-chapter-intro'>{ui.esc(chapter.intro)}</div>" if chapter.intro else ""
    )
    blocks = "".join(table_html(table, theme=theme) for table in chapter.tables)
    return f"""
    <section class="deep-chapter">
        <div class="deep-chapter-title">{ui.esc(chapter.title)}</div>
        {intro}
        {blocks}
    </section>
    """


def table_html(table: ReportTable, *, theme: PDFTheme) -> str:
    """Un tableau du canevas : intitulé numéroté, grille, avertissement."""
    _ = theme  # les couleurs viennent des variables CSS, pas d'un calcul ici
    subtitle = (
        f"<span class='deep-caption-sub'> — {ui.esc(table.subtitle)}</span>"
        if table.subtitle
        else ""
    )
    flag = "<span class='deep-flag'>À compléter manuellement</span>" if table.pending else ""
    caption = (
        f"<div class='deep-caption'>Tableau {table.number} · "
        f"{ui.esc(table.title)}{subtitle}{flag}</div>"
    )
    note = f"<div class='deep-note'>{ui.esc(table.note)}</div>" if table.note else ""

    if not table.rows:
        body = f"<div class='deep-empty'>{ui.esc(table.empty_message)}</div>"
        return f"<div class='deep-block'>{caption}{_head_only(table)}{body}{note}</div>"

    dense = " is-dense" if table.column_count > _DENSE_COLUMN_THRESHOLD else ""
    aligns = _column_aligns(table)
    rows_html = "".join(
        "<tr{cls}>{cells}</tr>".format(
            cls=' class="total-row"' if row.emphasis else "",
            cells="".join(
                f"<td class='{_cell_class(aligns, index)}'>{ui.esc(cell)}</td>"
                for index, cell in enumerate(row.cells)
            ),
        )
        for row in table.rows
    )
    return (
        f"<div class='deep-block'>{caption}"
        f"<table class='pdf-table deep-table{dense}'>{_thead(table)}"
        f"<tbody>{rows_html}</tbody></table>{note}</div>"
    )


def _head_only(table: ReportTable) -> str:
    """En-tête seul, pour les grilles vierges que l'école remplit à la main."""
    dense = " is-dense" if table.column_count > _DENSE_COLUMN_THRESHOLD else ""
    return f"<table class='pdf-table deep-table{dense}'>{_thead(table)}<tbody></tbody></table>"


def _thead(table: ReportTable) -> str:
    """En-tête sur un ou deux niveaux, selon que le tableau groupe ses colonnes."""
    if not table.has_grouped_header:
        cells = "".join(
            f"<th class='{_align_class(group.align)}'>{ui.esc(group.label)}</th>"
            for group in table.groups
        )
        return f"<thead><tr>{cells}</tr></thead>"

    top: list[str] = []
    bottom: list[str] = []
    for group in table.groups:
        align = _align_class(group.align)
        if group.subs:
            top.append(
                f"<th colspan='{len(group.subs)}' class='{align}'>{ui.esc(group.label)}</th>"
            )
            bottom.extend(f"<th class='{align}'>{ui.esc(sub)}</th>" for sub in group.subs)
        else:
            top.append(f"<th rowspan='2' class='{align}'>{ui.esc(group.label)}</th>")
    return f"<thead><tr>{''.join(top)}</tr><tr>{''.join(bottom)}</tr></thead>"


def _align_class(align: str) -> str:
    return "is-left" if align == "left" else ""


def _column_aligns(table: ReportTable) -> list[str]:
    """Alignement de chaque colonne, groupes dépliés — l'en-tête fait foi.

    Sans cela, une colonne de chiffres centrée dans son en-tête verrait ses
    valeurs collées à gauche : la grille se lit alors de travers, ce qui est
    exactement ce qu'une colonne de comptages ne pardonne pas.
    """
    aligns: list[str] = []
    for group in table.groups:
        aligns.extend([group.align] * group.width)
    return aligns


def _cell_class(aligns: list[str], index: int) -> str:
    align = aligns[index] if index < len(aligns) else "left"
    if align == "center":
        return "is-center"
    if align == "right":
        return "is-right"
    return ""


def _ordinal(trimester: int) -> str:
    """« 1er », « 2e », « 3e » — le canevas titre « 1er trimestre »."""
    return "1er" if trimester == 1 else f"{trimester}e"
