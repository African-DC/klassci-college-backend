"""Aggregator public des primitives PDF.

Re-exporte les composants depuis 3 sous-modules thématiques pour
respecter `no-god-code.md` (612 LOC → splitté 2026-05-18) :

- `_chrome.py`  — base_styles + CI_BANNER + premium_header + premium_footer
                  + signature_block
- `_blocks.py`  — section_title + status_pill + amount_box + kpi_card
                  + kpis_row + progress_bar + info_row + info_grid + meta_banner
- `_tables.py`  — premium_table + _render_cell (cell typing)

Les generators continuent d'importer via :
    from app.services.pdf import components as ui

Aucun call-site n'a besoin de changer.

Imports patterns :
    from app.services.pdf.theme import PDFTheme, status_label, method_label
    from app.services.pdf import components as ui
    from app.services.pdf._helpers import esc, format_decimal, image_to_datauri
"""

from __future__ import annotations

from app.services.pdf._blocks import (
    amount_box,
    info_grid,
    info_row,
    kpi_card,
    kpis_row,
    meta_banner,
    progress_bar,
    section_title,
    status_pill,
)
from app.services.pdf._chrome import (
    CI_BANNER_HTML,
    base_styles,
    document_frame,
    page_decoration,
    premium_footer,
    premium_header,
    seal_block,
    signatory_clause,
    signature_block,
)
from app.services.pdf._helpers import (
    enum_value,
    esc,
    format_decimal,
    image_to_datauri,
)
from app.services.pdf._tables import premium_table
from app.services.pdf.theme import method_label, status_label

__all__ = [
    "CI_BANNER_HTML",
    "amount_box",
    "base_styles",
    "document_frame",
    "enum_value",
    "esc",
    "format_decimal",
    "image_to_datauri",
    "info_grid",
    "info_row",
    "kpi_card",
    "kpis_row",
    "meta_banner",
    "method_label",
    "page_decoration",
    "premium_footer",
    "premium_header",
    "premium_table",
    "progress_bar",
    "seal_block",
    "section_title",
    "signatory_clause",
    "signature_block",
    "status_label",
    "status_pill",
]
