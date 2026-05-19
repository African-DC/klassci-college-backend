"""État individuel des frais — PDF premium pour parent/caissier.

Document synthétisant pour une inscription :
- Tous les frais dus (catégorie, montant, payé, reste, statut)
- Historique des versements (N° reçu, date, méthode, montant)
- KPIs : total attendu, total versé, reste à payer, % completion

Persona-first : Mariam Koné (parent) reçoit ce document après chaque
versement pour suivre l'avancement annuel.

Refactor 2026-05-18 : utilise `components.py` (header premium, kpis_row,
progress_bar, premium_table) + `PDFTheme` instancié depuis `school_settings`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import enum_value, format_decimal
from app.services.pdf.theme import PDFTheme, method_label


def _fmt(v: Any) -> str:
    """Format Decimal/scalar pour affichage XOF (sans symbole)."""
    if isinstance(v, Decimal):
        return format_decimal(v)
    if v in (None, ""):
        return "—"
    return str(v)


def _fee_rows(fees: list[dict[str, Any]]) -> list[list[Any]]:
    """Compose les rows premium_table : Catégorie / Montant / Versé / Reste / Statut."""
    rows: list[list[Any]] = []
    for f in fees:
        name = f.get("category_name", "")
        amount = f.get("amount")
        paid = f.get("paid", Decimal("0"))
        remaining = f.get("remaining")
        status_key = enum_value(f.get("status", "pending")) or "pending"
        rows.append(
            [
                name,
                {"value": _fmt(amount), "type": "num"},
                {"value": _fmt(paid), "type": "num"},
                {"value": _fmt(remaining), "type": "num-emphasis"},
                {"value": status_key, "type": "pill"},
            ]
        )
    return rows


def _payment_rows(payments: list[dict[str, Any]]) -> list[list[Any]]:
    """Compose les rows premium_table : N° / Date / Méthode / Référence / Montant / Statut."""
    rows: list[list[Any]] = []
    for p in payments:
        pay_id = p.get("id", "")
        created_at = p.get("created_at")
        date_str = (
            created_at.strftime("%d/%m/%Y")
            if isinstance(created_at, datetime)
            else str(created_at or "")
        )
        method_key = enum_value(p.get("method", "")) or ""
        reference = p.get("reference") or "—"
        amount = p.get("amount")
        status_key = enum_value(p.get("status", "completed")) or "completed"
        rows.append(
            [
                f"#{pay_id}",
                date_str,
                method_label(method_key),
                {"value": reference, "type": "muted"},
                {"value": _fmt(amount), "type": "num-emphasis"},
                {"value": status_key, "type": "pill"},
            ]
        )
    return rows


def generate_fee_statement_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère un état des frais individuel pour une inscription.

    data keys :
        student_name, class_name, academic_year_name, enrollment_id,
        fees: list[{category_name, amount, paid, remaining, status}],
        payments: list[{id, created_at, method, reference, amount, status}],
        totals: {total_expected, total_paid, total_remaining, completion_rate},
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)

    student_name = data.get("student_name", "")
    class_name = data.get("class_name", "")
    academic_year = data.get("academic_year_name", "")
    enrollment_id = data.get("enrollment_id", "")
    fees = data.get("fees", []) or []
    payments = data.get("payments", []) or []
    totals = data.get("totals", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y %H:%M")

    total_expected = totals.get("total_expected", Decimal("0"))
    total_paid = totals.get("total_paid", Decimal("0"))
    total_remaining = totals.get("total_remaining", Decimal("0"))
    completion_rate = float(totals.get("completion_rate", 0.0) or 0.0)

    meta_left = (
        f"<strong>Élève :</strong> {ui.esc(student_name)}<br/>"
        f"<strong>Classe :</strong> {ui.esc(class_name)}"
    )
    meta_right = (
        f"<strong>Année scolaire :</strong> {ui.esc(academic_year)}<br/>"
        f"<strong>Inscription N° {ui.esc(enrollment_id)}</strong> · édité le {ui.esc(issued_str)}"
    )

    kpis = ui.kpis_row(
        cards=[
            {"label": "Total attendu", "value": f"{_fmt(total_expected)} XOF"},
            {"label": "Total versé", "value": f"{_fmt(total_paid)} XOF", "tone": "success"},
            {"label": "Reste à payer", "value": f"{_fmt(total_remaining)} XOF", "tone": "accent"},
            {"label": "Avancement", "value": f"{completion_rate:.1f}%"},
        ],
        theme=theme,
    )

    fees_section = ui.section_title("Détail des frais", theme=theme) + ui.premium_table(
        headers=[
            "Catégorie",
            {"label": "Montant", "align": "right"},
            {"label": "Versé", "align": "right"},
            {"label": "Reste", "align": "right"},
            "Statut",
        ],
        rows=_fee_rows(fees),
        theme=theme,
        empty_message="Aucun frais configuré pour cette inscription.",
    )

    payments_section = ui.section_title(
        "Historique des versements", theme=theme
    ) + ui.premium_table(
        headers=[
            "N°",
            "Date",
            "Méthode",
            "Référence",
            {"label": "Montant", "align": "right"},
            "Statut",
        ],
        rows=_payment_rows(payments),
        theme=theme,
        empty_message="Aucun versement enregistré à ce jour.",
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size='A4', margin='15mm')}</head>
    <body>
        {ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="ÉTAT DES FRAIS SCOLAIRES",
            doc_subtitle=f"{class_name} — {academic_year}" if class_name else None,
        )}

        {ui.meta_banner(meta_left, meta_right, theme=theme)}

        {kpis}
        {ui.progress_bar(completion_rate, theme=theme)}

        {fees_section}

        {payments_section}

        {ui.premium_footer(
            school_settings,
            theme=theme,
            note="Document généré automatiquement — non contractuel sans signature.",
        )}
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
