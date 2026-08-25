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

from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Ordre partage avec l ecran caisse : une seule source de verite.
from app.core.payment_methods import ordered_methods
from app.services.pdf import components as ui
from app.services.pdf._helpers import enum_value, format_xof
from app.services.pdf.theme import PDFTheme, method_label

_JOURS_FR = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)
_MOIS_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def french_long_date(value: date | datetime | None) -> str:
    """« vendredi 21 août 2026 ».

    `strftime("%A %d %B %Y")` suit la locale du processus : sur le serveur,
    la locale C, d'où « Friday 21 August 2026 » en tête d'une pièce comptable
    française. Les noms sont donc portés ici, sans dépendre d'un `setlocale`
    global qui affecterait tout le processus.
    """
    if value is None:
        return ""
    return f"{_JOURS_FR[value.weekday()]} {value.day} {_MOIS_FR[value.month - 1]} {value.year}"


def _payment_rows(payments: list[dict[str, Any]], *, with_cashier: bool) -> list[list[Any]]:
    """Rows premium_table : N° / Heure / [Caissier] / Élève / Méthode / Réf / Montant / Statut.

    La colonne « Caissier » n'apparaît que sur le bordereau consolidé : sur
    celui d'une seule caisse, elle répéterait le même nom à chaque ligne.
    """
    rows: list[list[Any]] = []
    for p in payments:
        created_at = p.get("created_at")
        time_str = created_at.strftime("%H:%M") if isinstance(created_at, datetime) else ""
        student_name = p.get("student_name", "—")
        method_key = enum_value(p.get("method", "")) or ""
        reference = p.get("reference") or "—"
        amount = p.get("amount")
        amount_str = format_xof(amount) if isinstance(amount, Decimal) else str(amount or "—")
        status_key = enum_value(p.get("status", "completed")) or "completed"
        row: list[Any] = [
            f"#{p.get('id', '')}",
            {"value": time_str, "type": "muted"},
        ]
        if with_cashier:
            row.append({"value": p.get("cashier_name") or "—", "type": "muted"})
        row += [
            student_name,
            method_label(method_key),
            {"value": reference, "type": "muted"},
            {"value": amount_str, "type": "num-emphasis"},
            {"value": status_key, "type": "pill"},
        ]
        rows.append(row)
    return rows


def _annulations_section(payments: list[dict[str, Any]], *, theme: Any) -> str:
    """Les annulations du jour, avec leur motif.

    Elles ne rentrent pas dans le tableau principal : ajouter deux colonnes
    pour un cas rare le rendrait illisible les jours ou il n'y en a aucune.
    Mais elles ne peuvent pas non plus rester hors du document — un ecart
    constate a la cloture se justifie par ces lignes-la, et c'est ce
    bordereau qu'on relit pour les retrouver.
    """
    annulees = [p for p in payments if enum_value(p.get("status")) == "cancelled"]
    if not annulees:
        return ""

    lignes = []
    for p in annulees:
        montant = p.get("amount")
        lignes.append(
            [
                f"#{p.get('id', '')}",
                p.get("student_name") or "—",
                {
                    "value": format_xof(montant) if isinstance(montant, Decimal) else "—",
                    "type": "num",
                },
                {"value": p.get("cancelled_by_name") or "—", "type": "muted"},
                p.get("cancellation_reason") or "—",
            ]
        )

    return ui.section_title("Annulations du jour", theme=theme) + ui.premium_table(
        headers=["N°", "Élève", "Montant", "Annulé par", "Motif"],
        rows=lignes,
        theme=theme,
        empty_message="",
    )


def _cashier_methods(by_cashier: list[Any]) -> list[str]:
    """Les colonnes du tableau par caisse, dans l'ordre metier.

    Tirees de ce qui a reellement ete encaisse, jamais d'une constante : un
    moyen absent de la liste figee disparaissait des colonnes pendant que le
    total continuait de le compter, et le bordereau se contredisait.
    """
    presents: set[str] = set()
    for entry in by_cashier:
        presents.update(str(k) for k in (getattr(entry, "by_method", None) or {}))
    return ordered_methods(presents)


def _by_cashier_rows(by_cashier: list[Any], methods: list[str]) -> list[list[Any]]:
    """Une ligne par caisse : versements, ventilation par moyen, total."""
    rows: list[list[Any]] = []
    for entry in by_cashier:
        cells: list[Any] = [
            entry.cashier_name,
            {"value": str(entry.count), "type": "num"},
        ]
        for method in methods:
            amount = entry.by_method.get(method, Decimal("0"))
            cells.append({"value": format_xof(amount), "type": "num"})
        cells.append({"value": format_xof(entry.total), "type": "num-emphasis"})
        rows.append(cells)
    return rows


def _totals_rows(totals_by_method: dict[str, Decimal]) -> list[list[Any]]:
    """Rows pour récap par méthode — ce qui a été encaissé, dans l'ordre métier.

    Les lignes viennent des montants réellement collectés, l'ordre seulement
    de `DISPLAY_ORDER`. Parcourir la constante pour y piocher les montants
    omettait purement et simplement du récapitulatif tout moyen qui n'y
    figurait pas, pendant que « Total encaissé ce jour » continuait de le
    compter : le bordereau se contredisait lui-même, et c'est le document que
    la comptabilité contresigne.
    """
    return [
        [
            method_label(m),
            {"value": format_xof(totals_by_method[m]), "type": "num"},
        ]
        for m in ordered_methods(totals_by_method)
    ]


def generate_daily_cash_book_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Génère le bordereau journalier pour une date donnée.

    Deux documents en un, selon `consolidated` :
    - la caisse d'une personne, qu'elle imprime pour clôturer sa journée ;
    - la consolidation de toutes les caisses, que le comptable édite pour son
      point journalier — avec la ventilation par caisse et par moyen.

    data keys :
        date: datetime.date (du bordereau)
        consolidated: bool — True = toutes les caisses
        cashier_name: str | None — la caisse concernée, si une seule
        issued_by_name: str — qui a édité le document
        payments: list[{id, created_at, student_name, cashier_name, method,
                        reference, amount, status}]
        by_cashier: list[CashierDayTotals] — ventilation, si consolidé
        totals_by_method: {cash: Decimal, mobile_money: Decimal, ...}
        total_general: Decimal
        count_completed: int
        count_cancelled: int
        issued_at: datetime
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    date_str = french_long_date(data.get("date"))

    consolidated = bool(data.get("consolidated"))
    by_cashier = data.get("by_cashier", []) or []
    issued_by_name = data.get("issued_by_name") or "—"
    cashier_name = data.get("cashier_name") or "—"
    payments = data.get("payments", []) or []
    totals_by_method = data.get("totals_by_method", {}) or {}
    total_general = data.get("total_general", Decimal("0"))
    count_completed = int(data.get("count_completed", 0) or 0)
    count_cancelled = int(data.get("count_cancelled", 0) or 0)
    issued_at = data.get("issued_at") or datetime.utcnow()
    issued_str = issued_at.strftime("%d/%m/%Y %H:%M")

    # Sur le document consolidé, nommer un caissier serait faux : il couvre
    # toutes les caisses de la journée. Il portait jusqu'ici le nom de la
    # personne qui l'imprimait — le comptable se retrouvait désigné caissier
    # sur une pièce qui récapitule le travail de trois autres.
    if consolidated:
        nb = len(by_cashier)
        caisses = f"{nb} caisse{'s' if nb > 1 else ''}" if nb else "aucune caisse"
        meta_left = f"<strong>Toutes les caisses</strong> · {ui.esc(caisses)}"
    else:
        meta_left = f"<strong>Caissier :</strong> {ui.esc(cashier_name)}"
    # « par — » se lit comme un champ casse. Sans nom, on n'annonce pas
    # l'auteur : la date suffit, et le bordereau porte deja la signature.
    meta_right = f"Édité le {ui.esc(issued_str)}"
    if issued_by_name and issued_by_name.strip() not in ("—", "-"):
        meta_right += f" par {ui.esc(issued_by_name)}"

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
        format_xof(total_general) if isinstance(total_general, Decimal) else str(total_general)
    )

    method_section = ui.section_title("Récapitulatif par méthode", theme=theme) + ui.premium_table(
        headers=["Méthode", {"label": "Total XOF", "align": "right"}],
        rows=_totals_rows(totals_by_method),
        theme=theme,
        empty_message="Aucun versement encaissé ce jour.",
    )

    # Ventilation par caisse : le cœur du point journalier du comptable.
    # Inutile sur le bordereau d'un seul caissier, où elle répéterait
    # exactement le récapitulatif par méthode.
    cashier_section = ""
    if consolidated:
        # Une seule liste de colonnes pour l'en-tete et les cellules : deux
        # parcours separes finissent par decaler les montants d'une colonne.
        cashier_methods = _cashier_methods(by_cashier)
        cashier_section = ui.section_title(
            "Récapitulatif par caisse", theme=theme
        ) + ui.premium_table(
            headers=[
                "Caissier",
                {"label": "Versements", "align": "right"},
                *({"label": method_label(method), "align": "right"} for method in cashier_methods),
                {"label": "Total XOF", "align": "right"},
            ],
            rows=_by_cashier_rows(by_cashier, cashier_methods),
            theme=theme,
            empty_message="Aucune caisse n'a encaissé ce jour.",
        )

    detail_headers: list[Any] = ["N°", "Heure"]
    if consolidated:
        detail_headers.append("Caissier")
    detail_headers += [
        "Élève",
        "Méthode",
        "Référence",
        {"label": "Montant", "align": "right"},
        "Statut",
    ]

    annulations_section = _annulations_section(payments, theme=theme)

    detail_section = ui.section_title("Détail des versements", theme=theme) + ui.premium_table(
        headers=detail_headers,
        rows=_payment_rows(payments, with_cashier=consolidated),
        theme=theme,
        empty_message="Aucun versement encaissé ce jour.",
    )

    # Qui signe quoi : le caissier arrête sa propre caisse, le comptable
    # arrête la consolidation. Faire signer « Le Caissier » sous un document
    # qui couvre trois caisses n'engage personne.
    signature_roles = (
        [{"role": "La Comptabilité", "name": issued_by_name}, {"role": "La Direction"}]
        if consolidated
        else [{"role": "Le Caissier", "name": cashier_name}, {"role": "La Comptabilité"}]
    )
    signatures = ui.signature_block(roles=signature_roles, theme=theme)

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="14mm")}</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
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

        {cashier_section}

        {detail_section}

        {annulations_section}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note="À conserver pour la comptabilité de l'établissement.",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
