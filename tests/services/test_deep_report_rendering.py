"""Rendu HTML des tableaux DEEP — cohérence des en-têtes à deux niveaux.

Un en-tête groupé mal compté décale silencieusement toute la grille à
l'impression : les chiffres sont bons, mais sous la mauvaise colonne. Le test
compare le nombre de colonnes déclarées à celui des cellules réellement
posées.
"""

from __future__ import annotations

from app.services.deep_report._types import (
    PENDING_NOTE,
    DeepReport,
    HeaderGroup,
    ReportChapter,
    ReportRow,
    ReportTable,
    simple_headers,
)
from app.services.pdf import _deep_report_parts as parts
from app.services.pdf import components as ui
from app.services.pdf.theme import PDFTheme

_THEME = PDFTheme.from_school({"school_name": "Lycée test"})

_GROUPED = ReportTable(
    number=5,
    title="Récapitulatif",
    groups=(
        HeaderGroup("Classes"),
        HeaderGroup("Effectifs réels", subs=("F", "G", "T"), align="center"),
        HeaderGroup("Moy ≥ 10", subs=("Nombre", "%"), align="center"),
    ),
    rows=(
        ReportRow(cells=("6ème A", "10", "12", "22", "18", "81,8 %")),
        ReportRow(cells=("TOTAL", "10", "12", "22", "18", "81,8 %"), emphasis=True),
    ),
)


def test_nombre_de_colonnes_declarees():
    assert _GROUPED.column_count == 6
    assert _GROUPED.has_grouped_header is True


def test_entete_groupe_produit_deux_lignes():
    html = parts.table_html(_GROUPED, theme=_THEME)
    assert html.count("<tr>") >= 2
    # La colonne simple est fusionnée verticalement, les groupes s'étalent.
    assert "rowspan='2'" in html
    assert "colspan='3'" in html
    assert "colspan='2'" in html


def test_ligne_de_total_est_marquee():
    html = parts.table_html(_GROUPED, theme=_THEME)
    assert 'class="total-row"' in html


def test_entete_simple_tient_sur_une_ligne():
    table = ReportTable(
        number=9,
        title="Transferts",
        groups=simple_headers("N°", "Nom et Prénoms", "Classe"),
        rows=(ReportRow(cells=("1", "Koné Awa", "6ème A")),),
    )
    html = parts.table_html(table, theme=_THEME)
    assert "rowspan" not in html
    assert "colspan" not in html


def test_tableau_vide_affiche_son_message_et_pas_des_zeros():
    table = ReportTable(
        number=24,
        title="Décès",
        groups=simple_headers("N°", "Nom et Prénoms"),
        pending=True,
        note=f"{PENDING_NOTE} sur le document imprimé.",
        empty_message=f"{PENDING_NOTE} — aucune donnée collectée.",
    )
    html = parts.table_html(table, theme=_THEME)
    assert "deep-empty" in html
    assert PENDING_NOTE in html
    assert "deep-flag" in html
    assert "<td>0</td>" not in html


def test_les_tableaux_a_completer_sont_recenses():
    """Le recensement suit un drapeau, pas une tournure de phrase.

    Un tableau simplement vide — aucun transfert cette année — n'est pas un
    tableau que la plateforme ne sait pas produire.
    """
    report = DeepReport(
        academic_year_name="2025-2026",
        trimester=1,
        chapters=[
            ReportChapter(
                title="Chapitre IV",
                tables=(
                    ReportTable(
                        number=24,
                        title="Décès",
                        groups=simple_headers("N°"),
                        pending=True,
                        note=f"{PENDING_NOTE.lower()}.",
                    ),
                    ReportTable(
                        number=9,
                        title="Transferts",
                        groups=simple_headers("N°"),
                        note=f"Aucun transfert — {PENDING_NOTE.lower()} le cas échéant.",
                    ),
                ),
            )
        ],
    )
    assert report.pending_table_numbers == [24]


def test_page_de_garde_reprend_l_entete_officiel():
    report = DeepReport(academic_year_name="2025-2026", trimester=1)
    html = parts.cover_html(
        {"school_name": "Lycée Saint-Augustin", "ministry_code": "CI-0421"},
        report,
        issued_on="20/08/2026",
    )
    assert "Direction de l'Encadrement des Établissements Privés" in html
    assert "1er trimestre" in html
    assert "Lycée Saint-Augustin" in html
    assert "CI-0421" in html


def test_lignes_rayees_sans_selecteur_nth_child() -> None:
    """Le rapport DEEP raye ses lignes par classe : `nth-child` coûtait 87 s de rendu."""
    table = ReportTable(
        number=7,
        title="Liste",
        groups=simple_headers("Élève", "Moyenne"),
        rows=(
            ReportRow(cells=("A", "12")),
            ReportRow(cells=("B", "11")),
            ReportRow(cells=("C", "10")),
            ReportRow(cells=("TOTAL", "11"), emphasis=True),
        ),
    )
    html = parts.table_html(table, theme=_THEME)
    rows = html.split("<tr")[1:]
    body = [r for r in rows if "<td" in r]

    assert [('class="alt"' in r) for r in body] == [False, True, False, False]
    assert 'class="total-row"' in body[-1]

    styles = ui.base_styles(_THEME, zebra_selector=False)
    assert "nth-child" not in styles
    assert "tr.alt td" in styles
    assert "nth-child(even)" in ui.base_styles(_THEME)
