"""Blocs PDF : titles, pills, montants, KPIs, progress, info grid, meta banner.

Exporté via `components.py` (aggregator). Ne pas importer ce module
directement depuis les generators : utiliser
`from app.services.pdf import components as ui`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.pdf._helpers import esc, format_decimal
from app.services.pdf.theme import PDFTheme, status_label


def section_title(label: str, *, theme: PDFTheme) -> str:
    """Titre de section : uppercase primary + bordure bottom primary."""
    return f'<div class="pdf-section-title">{esc(label)}</div>'


def status_pill(status_key: str, *, label: str | None = None) -> str:
    """Pill colorée sémantique. `status_key` détermine la classe CSS.

    Si `label` n'est pas fourni, utilise `status_label(status_key)` pour
    obtenir le FR (ex: paid → "Payé").
    """
    key = (status_key or "").lower()
    text = esc(label) if label else esc(status_label(key))
    return f'<span class="pdf-pill pdf-pill-{esc(key)}">{text}</span>'


def amount_box(
    amount: Any,
    *,
    theme: PDFTheme,
    label: str = "Montant",
    currency: str = "XOF",
) -> str:
    """Box gros montant centré gradient KLASSCI."""
    amount_str = format_decimal(amount) if isinstance(amount, Decimal) else esc(str(amount))
    return f"""
    <div class="pdf-amount-box">
        <div class="pdf-amount-label">{esc(label)}</div>
        <div class="pdf-amount-value">{amount_str} {esc(currency)}</div>
    </div>
    """


def _valeur_non_nulle(valeur: str) -> bool:
    """Vrai si la valeur affichee porte autre chose que des zeros."""
    return any(c in "123456789" for c in str(valeur))


def kpi_card(
    label: str,
    value: str,
    *,
    theme: PDFTheme,
    tone: str = "primary",
) -> str:
    """KPI card unique. `tone` parmi primary/accent/success/warn.

    Un ton semantique sur une valeur nulle est retrograde en neutre : « 0 %
    de reussite » ou « 0 XOF verse » ecrit en vert dit « tout va bien », et
    l'oeil lit la couleur avant le chiffre. Mieux vaut pas de signal qu'un
    signal faux.
    """
    if tone in ("success", "warn") and not _valeur_non_nulle(value):
        tone = "primary"
    value_class = (
        f"pdf-kpi-value pdf-kpi-value-{esc(tone)}" if tone != "primary" else "pdf-kpi-value"
    )
    return f"""
    <div class="pdf-kpi">
        <div class="pdf-kpi-label">{esc(label)}</div>
        <div class="{value_class}">{esc(value)}</div>
    </div>
    """


def kpis_row(cards: list[dict[str, Any]], *, theme: PDFTheme) -> str:
    """Row de KPI cards. Chaque card : {"label": str, "value": str, "tone": str?}."""
    if not cards:
        return ""
    inner = "".join(
        kpi_card(
            c.get("label", ""),
            c.get("value", ""),
            theme=theme,
            tone=c.get("tone", "primary"),
        )
        for c in cards
    )
    return f'<div class="pdf-kpis">{inner}</div>'


def progress_bar(percentage: float, *, theme: PDFTheme) -> str:
    """Barre de progression linear gradient primary→accent. Clamp 0-100."""
    pct = max(0, min(100, percentage))
    return f"""
    <div class="pdf-progress">
        <div class="pdf-progress-fill" style="width:{pct:.1f}%;"></div>
    </div>
    """


def info_row(label: str, value: Any) -> str:
    """Ligne 2-col : label (muted/uppercase) + value."""
    val = esc(str(value)) if value not in (None, "") else "—"
    return f"""
    <div class="pdf-info-row">
        <span class="pdf-info-label">{esc(label)}</span>
        <span class="pdf-info-value">{val}</span>
    </div>
    """


def info_grid(items: list[tuple[str, Any]], *, columns: int = 2) -> str:
    """Grille info N-colonnes (default 2). Items = [(label, value), ...]."""
    rows = "".join(info_row(lbl, val) for lbl, val in items)
    return (
        f'<div class="pdf-info-grid" '
        f'style="grid-template-columns:repeat({columns}, 1fr);">{rows}</div>'
    )


def info_table(items: list[tuple[str, Any]]) -> str:
    """Bloc label/valeur en table borderless — alignement colonne robuste.

    Rend un vrai ``<table>`` deux colonnes plutôt qu'un flex : le support
    flexbox de WeasyPrint est partiel et laisse l'étiquette rétrécir à son
    contenu, si bien que les valeurs ne s'alignent plus verticalement. Une
    table garantit une colonne d'étiquettes de largeur fixe et des valeurs
    parfaitement alignées, sans bordure.

    La valeur peut être du HTML déjà composé (ex. un status pill) via un
    dict ``{"html": "<span ...>"}`` ; sinon elle est échappée.
    """
    rows: list[str] = []
    for label, value in items:
        if isinstance(value, dict) and "html" in value:
            val_html = str(value["html"])
        else:
            val_html = esc(str(value)) if value not in (None, "") else "—"
        rows.append(
            f'<tr><td class="pdf-info-label">{esc(label)}</td>'
            f'<td class="pdf-info-value">{val_html}</td></tr>'
        )
    return f'<table class="pdf-info-table">{"".join(rows)}</table>'


def entitlements_note(
    lignes: list[tuple[str, str]],
    *,
    theme: PDFTheme,
    title: str = "CE QUE CES FRAIS OUVRENT",
    overflow: int = 0,
) -> str:
    """Bloc court « ce que la famille obtient », une ligne par frais.

    Dimensionne pour un recu imprime en deux exemplaires sur une A4 coupee au
    milieu : une demi-page fait 148 mm, dont la situation financiere de
    l'eleve occupe deja la moitie. Le bloc se tient donc a 7 pt, une ligne par
    categorie, et ne s'affiche pas du tout quand il n'y a rien a promettre —
    plutot qu'un titre suivi du vide, qui inquieterait plus qu'il ne rassure.

    `overflow` compte les frais regles ce jour qui n'ont pas trouve leur place :
    on les annonce en une ligne au lieu de les taire.
    """
    lignes_utiles = [(nom, texte) for nom, texte in lignes if texte]
    if not lignes_utiles:
        return ""

    corps = "".join(
        f'<div style="margin:0 0 1mm 0; line-height:1.3;">'
        f'<span style="font-weight:700; color:{theme.primary};">{esc(nom)}</span>'
        f'<span style="color:var(--muted);"> · </span>{esc(texte)}</div>'
        for nom, texte in lignes_utiles
    )
    reste = (
        f'<div style="color:var(--muted); font-style:italic;">'
        f"et {overflow} autre{'s' if overflow > 1 else ''} frais "
        f"régl{'és' if overflow > 1 else 'é'} ce jour</div>"
        if overflow > 0
        else ""
    )
    return (
        f'<div style="margin:3mm 0 0 0; padding:2mm 2.5mm; font-size:7pt;'
        f" background:{theme.primary_light}; border-left:0.8mm solid {theme.accent};"
        f' border-radius:0 1.5mm 1.5mm 0;">'
        f'<div style="font-size:6.5pt; font-weight:700; letter-spacing:0.4pt;'
        f' text-transform:uppercase; color:{theme.primary}; margin-bottom:1.2mm;">'
        f"{esc(title)}</div>"
        f"{corps}{reste}</div>"
    )


def meta_banner(left: str, right: str = "", *, theme: PDFTheme) -> str:
    """Panneau gradient compact entre header et content principal."""
    right_html = (
        f'<div style="text-align:right; color:var(--muted);">{right}</div>' if right else ""
    )
    return f"""
    <div style="background:linear-gradient(135deg, var(--soft-bg), #eef2ff);
                border:1px solid var(--primary); border-radius:6px;
                padding:8px 12px; margin:6px 0 12px;
                display:flex; justify-content:space-between; gap:10px;
                font-size:10px;">
        <div style="flex:1;">{left}</div>
        {right_html}
    </div>
    """
