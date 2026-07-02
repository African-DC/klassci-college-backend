"""Reçu de paiement — PDF A5 premium avec breakdown allocation + theme école dynamique.

Refactor 2026-05-18 : utilise `components.py` (header premium, amount_box,
section_title, premium_table, signature_block, footer) + `PDFTheme` instancié
depuis `school_settings` pour personnalisation tenant (couleurs école).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc, format_decimal
from app.services.pdf.theme import PDFTheme, method_label, status_label


def _allocations_rows(allocations: list[dict[str, Any]]) -> list[list[Any]]:
    """Compose les rows premium_table pour le breakdown allocation."""
    rows: list[list[Any]] = []
    for a in allocations:
        fee_name = a.get("fee_name", "")
        amount = a.get("amount")
        amount_str = (
            format_decimal(amount)
            if isinstance(amount, Decimal)
            else str(amount)
            if amount is not None
            else "—"
        )
        paid_after = a.get("fee_paid_after")
        fee_total = a.get("fee_total")
        cumul = ""
        if paid_after is not None and fee_total is not None:
            paid_str = (
                format_decimal(paid_after) if isinstance(paid_after, Decimal) else str(paid_after)
            )
            total_str = (
                format_decimal(fee_total) if isinstance(fee_total, Decimal) else str(fee_total)
            )
            cumul = f"{paid_str} / {total_str}"
        status_key = a.get("status_after", "")
        rows.append(
            [
                fee_name,
                {"value": f"+ {amount_str}", "type": "num-emphasis"},
                {"value": cumul, "type": "muted"},
                {"value": status_key, "type": "pill"},
            ]
        )
    return rows


def generate_receipt_pdf(payment_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Generate a payment receipt PDF — premium template + theme école dynamique.

    payment_data keys: payment_id, amount, method, reference, status, notes,
        student_name, fee_description, created_at, received_by_name, allocations.
    school_settings keys: school_name, ministry_code, address, phone, email,
        logo_url, signature_image_url, head_master_name, head_master_title,
        primary_color, accent_color, website, motto.
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    payment_id = payment_data.get("payment_id", "")
    amount = payment_data.get("amount")
    method_key = payment_data.get("method", "")
    reference = payment_data.get("reference") or ""
    status_key = payment_data.get("status", "")
    notes = payment_data.get("notes") or ""
    student_name = payment_data.get("student_name", "")
    fee_description = payment_data.get("fee_description", "")
    created_at = payment_data.get("created_at")
    received_by = payment_data.get("received_by_name") or "—"
    allocations = payment_data.get("allocations") or []

    amount_str = format_decimal(amount) if isinstance(amount, Decimal) else str(amount or "—")
    pay_date = (
        created_at.strftime("%d/%m/%Y à %H:%M")
        if isinstance(created_at, datetime)
        else str(created_at or "")
    )

    # Méthode et statut affichés en FR via les labels
    method_display = method_label(method_key)
    status_display = status_label(status_key)

    # Info grid : élève + nature + méthode + ref + statut + notes
    info_items: list[tuple[str, Any]] = [
        ("Élève", student_name),
        ("Nature", fee_description),
        ("Méthode", method_display),
    ]
    if reference:
        info_items.append(("Référence", reference))
    info_items.append(("Statut", ui.status_pill(status_key, label=status_display)))
    if notes:
        info_items.append(("Notes", notes))

    info_html = (
        '<div class="pdf-info-grid" style="grid-template-columns:1fr;">'
        + "".join(
            ui.info_row(lbl, val)
            if not (isinstance(val, str) and val.startswith("<span"))
            else f'<div class="pdf-info-row"><span class="pdf-info-label">{esc(lbl)}</span><span class="pdf-info-value">{val}</span></div>'
            for lbl, val in info_items
        )
        + "</div>"
    )

    # Allocations section (optionnelle)
    allocations_section = ""
    if allocations:
        rows = _allocations_rows(allocations)
        allocations_section = ui.section_title(
            "Détail de l'allocation", theme=theme
        ) + ui.premium_table(
            headers=[
                "Frais",
                {"label": "Affecté", "align": "right"},
                {"label": "Cumul après", "align": "right"},
                "Statut",
            ],
            rows=rows,
            theme=theme,
            col_widths=["40%", "20%", "22%", "18%"],
        )

    # Signatures
    signatures_html = ui.signature_block(
        roles=[
            {"role": "Le Caissier", "name": received_by},
            {"role": "Le Parent / Tuteur"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A5", margin="12mm")}</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="REÇU DE VERSEMENT",
            doc_number=f"N° {payment_id} · {pay_date}",
        )
    }

        {ui.amount_box(amount_str, theme=theme, label="Montant versé", currency="XOF")}

        {info_html}

        {allocations_section}

        {signatures_html}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="Ce reçu fait foi de paiement. À conserver précieusement.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
