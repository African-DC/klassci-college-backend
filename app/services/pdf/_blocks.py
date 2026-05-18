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
    amount_str = (
        format_decimal(amount) if isinstance(amount, Decimal) else esc(str(amount))
    )
    return f"""
    <div class="pdf-amount-box">
        <div class="pdf-amount-label">{esc(label)}</div>
        <div class="pdf-amount-value">{amount_str} {esc(currency)}</div>
    </div>
    """


def kpi_card(
    label: str,
    value: str,
    *,
    theme: PDFTheme,
    tone: str = "primary",
) -> str:
    """KPI card unique. `tone` parmi primary/accent/success/warn."""
    value_class = (
        f"pdf-kpi-value pdf-kpi-value-{esc(tone)}"
        if tone != "primary"
        else "pdf-kpi-value"
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


def meta_banner(left: str, right: str = "", *, theme: PDFTheme) -> str:
    """Panneau gradient compact entre header et content principal."""
    right_html = (
        f'<div style="text-align:right; color:var(--muted);">{right}</div>'
        if right
        else ""
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
