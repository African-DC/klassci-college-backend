"""Bordereau journalier — récap des versements d'une date pour le caissier.

Document comptable de fin de journée :
- Total général encaissé + comptage validés/annulés
- Récapitulatif par méthode (espèces / mobile / virement / chèque)
- Détail de chaque versement (heure, élève, méthode, référence, montant)
- Signatures caissier + comptabilité

Persona : Mme Diallo (secrétaire/caissière) clôture sa journée.

Refactor 2026-05-18 : utilise `components.py` + `PDFTheme.from_school`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import enum_value, format_decimal
from app.services.pdf.theme import PDFTheme, method_label

_METHODS_ORDER = ["cash", "mobile_money", "bank_transfer", "cheque"]


def _payment_rows(payments: list[dict[str, Any]]) -> list[list[Any]]:
    """Rows premium_table : N° / Heure / Élève / Méthode / Référence / Montant / Statut."""
    rows: list[list[Any]] = []
    for p in payments:
        created_at = p.get("created_at")
        time_str = created_at.strftime("%H:%M") if isinstance(created_at, datetime) else ""
        student_name = p.get("student_name", "—")
        method_key = enum_value(p.get("method", "")) or ""
        reference = p.get("reference") or "—"
        amount = p.get("amount")
        amount_str = format_decimal(amount) if isinstance(amount, Decimal) else str(amount or "—")
        status_key = enum_value(p.get("status", "completed")) or "completed"
        rows.append(
            [
                f"#{p.get('id', '')}",
                {"value": time_str, "type": "muted"},
                student_name,
                method_label(method_key),
                {"value": reference, "type": "muted"},
                {"value": amount_str, "type": "num-emphasis"},
                {"value": status_key, "type": "pill"},
            ]
        )
    return rows


def _totals_rows(totals_by_method: dict[str, Decimal]) -> list[list[Any]]:
    """Rows pour récap par méthode."""
    rows: list[list[Any]] = []
    for m in _METHODS_ORDER:
        amount = totals_by_method.get(m, Decimal("0"))
        rows.append(
            [
                method_label(m),
                {"value": format_decimal(amount), "type": "num"},
            ]
        )
    return rows


def generate_daily_cash_book_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère le bordereau journalier pour une date donnée.

    data keys :
        date: datetime.date (du bordereau)
        cashier_name: str
        payments: list[{id, created_at, student_name, method, reference, amount, status}]
        totals_by_method: {cash: Decimal, mobile_money: Decimal, ...}
        total_general: Decimal
        count_completed: int
        count_cancelled: int
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)

    date_val = data.get("date")
    date_str = (
        date_val.strftime("%A %d %B %Y")
        if isinstance(date_val, datetime)
        else (date_val.strftime("%A %d %B %Y") if date_val else "")
    )

    cashier_name = data.get("cashier_name", "—")
    payments = data.get("payments", []) or []
    totals_by_method = data.get("totals_by_method", {}) or {}
    total_general = data.get("total_general", Decimal("0"))
    count_completed = int(data.get("count_completed", 0) or 0)
    count_cancelled = int(data.get("count_cancelled", 0) or 0)
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y %H:%M")

    meta_left = f"<strong>Caissier :</strong> {ui.esc(cashier_name)}"
    meta_right = f"Édité le {ui.esc(issued_str)}"

    # Sous-ligne du total : counts validés/annulés
    counts_pieces = [
        f"{count_completed} versement{'s' if count_completed > 1 else ''} validé{'s' if count_completed > 1 else ''}",
    ]
    if count_cancelled:
        counts_pieces.append(f"{count_cancelled} annulé{'s' if count_cancelled > 1 else ''}")
    counts_line = (
        '<div class="muted text-center" style="font-size:9px; margin:-8px 0 12px;">'
        + " · ".join(ui.esc(p) for p in counts_pieces)
        + "</div>"
    )

    total_str = (
        format_decimal(total_general) if isinstance(total_general, Decimal) else str(total_general)
    )

    method_section = ui.section_title("Récapitulatif par méthode", theme=theme) + ui.premium_table(
        headers=["Méthode", {"label": "Total XOF", "align": "right"}],
        rows=_totals_rows(totals_by_method),
        theme=theme,
    )

    detail_section = ui.section_title("Détail des versements", theme=theme) + ui.premium_table(
        headers=[
            "N°",
            "Heure",
            "Élève",
            "Méthode",
            "Référence",
            {"label": "Montant", "align": "right"},
            "Statut",
        ],
        rows=_payment_rows(payments),
        theme=theme,
        empty_message="Aucun versement encaissé ce jour.",
    )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Caissier", "name": cashier_name},
            {"role": "La Comptabilité"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="14mm")}</head>
    <body>
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="BORDEREAU JOURNALIER",
            doc_subtitle=date_str,
        )
    }

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {ui.amount_box(total_str, theme=theme, label="Total encaissé ce jour", currency="XOF")}
        {counts_line}

        {method_section}

        {detail_section}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="À conserver pour la comptabilité de l'établissement.",
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
