"""Le point d'une catégorie de frais — document officiel de l'établissement.

Même gabarit que le journal des versements ou le bulletin : bandeau République,
en-tête à l'identité de l'école, couleurs et logo tirés de ses paramètres, pied
institutionnel. Ce n'est pas de la décoration. Ce document part chez un
prestataire pour justifier un virement, ou sur un bureau pour préparer des
relances : un tableau blanc sans en-tête n'est pas une pièce, c'est un
brouillon.

**Deux mentions portent la valeur du document, et aucune n'est décorative.**

L'avertissement de cloisonnement, quand le lecteur ne voit qu'une caisse : sans
lui, un état de guichet se lit comme le compte de l'école entière. Il est en
haut, avant les totaux, et répété en pied pour qui feuillette par la fin.

Et la phrase sur les dépôts : l'application enregistre un dépôt par ligne de
frais, jamais une quantité. Un document qui parlerait de « paquets » promettrait
un décompte que la base ne tient pas, et c'est sur cette promesse qu'on
commanderait une livraison.
"""

from __future__ import annotations

from typing import Any

from weasyprint import HTML

from app.services.fee_category_ledger import CategoryLedger
from app.services.pdf import components as ui
from app.services.pdf._helpers import format_xof
from app.services.pdf.theme import PDFTheme

_COL_WIDTHS = ["26%", "13%", "11%", "16%", "11%", "12%", "11%"]

_ETAT: dict[str, str] = {
    "paid": "Soldé",
    "partial": "Partiel",
    "pending": "Dû",
    "in_kind": "Déposé en nature",
    "waived": "Exonéré",
}

_STYLES = """
<style>
    /* L'en-tête se répète : une page de montants sans nom de colonne ne se
       relit pas, et ce document se relit devant un fournisseur. */
    .pdf-table thead { display: table-header-group; }
    .pdf-table tr { break-inside: avoid; }
    .pdf-section-title { break-after: avoid; }
</style>
"""


def _periode(ledger: CategoryLedger) -> str:
    if ledger.date_from and ledger.date_to:
        return f"Du {ledger.date_from:%d/%m/%Y} au {ledger.date_to:%d/%m/%Y}"
    if ledger.date_from:
        return f"À partir du {ledger.date_from:%d/%m/%Y}"
    if ledger.date_to:
        return f"Jusqu'au {ledger.date_to:%d/%m/%Y}"
    return "Depuis le début de l'année"


def _avertissement_cloisonnement(ledger: CategoryLedger) -> str:
    """La ligne qui empêche de prendre un état de guichet pour celui de l'école."""
    if ledger.consolide:
        return ""
    return (
        '<div style="border-left:3px solid var(--warn); background:var(--soft-bg);'
        ' padding:8px 12px; margin:10px 0; font-size:9.5px;">'
        "<strong>Ce document ne couvre que votre caisse.</strong> Il dit ce que vous "
        "avez encaissé sur ce frais, et rien de ce qui a été encaissé ailleurs. "
        "Le reste à payer n'y figure donc pas : le calculer sur une seule caisse "
        "annoncerait une dette chez des familles ayant payé à un autre guichet."
        "</div>"
    )


def _note_depots(ledger: CategoryLedger) -> str:
    if not ledger.accepts_in_kind:
        return ""
    return (
        '<div class="muted" style="font-size:9px; margin:-4px 0 10px;">'
        f"Dépôts en nature sur la période : <strong>{ledger.depots_en_nature}</strong>. "
        "Un dépôt vaut une ligne de frais remise, jamais une quantité d'articles."
        "</div>"
    )


def _lignes(ledger: CategoryLedger) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for ligne in ledger.lignes:
        eleve = f"{ligne.last_name} {ligne.first_name}".strip()
        rows.append(
            [
                eleve,
                {"value": ligne.student_matricule or "—", "type": "muted"},
                {"value": ligne.class_name or "—", "type": "muted"},
                {"value": _ETAT.get(ligne.status, ligne.status), "type": "pill"},
                {"value": format_xof(ligne.due), "type": "num"},
                {"value": format_xof(ligne.paid) if ligne.paid else "—", "type": "num-emphasis"},
                # Un tiret, pas un zéro : sur une seule caisse on ne sait pas,
                # et un zéro se lirait comme un solde.
                {
                    "value": format_xof(ligne.remaining) if ligne.remaining else "—",
                    "type": "num",
                },
            ]
        )
    return rows


def render_fee_category_ledger_html(ledger: CategoryLedger, school_settings: dict[str, Any]) -> str:
    """Compose le document, sans le convertir en PDF.

    Séparé de la conversion pour que la composition se vérifie sans dépendre
    des bibliothèques natives de rendu — celles-là mêmes qui manquent sur un
    poste Windows.
    """
    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    meta_gauche = f"<strong>Périmètre :</strong> {ui.esc(ledger.class_name)}"
    if not ledger.consolide:
        meta_gauche += '<br/><span class="muted">Votre caisse uniquement</span>'
    meta_droite = f"Édité le {ui.esc(_maintenant())}"

    detail = ui.section_title("Détail par élève", theme=theme) + ui.premium_table(
        headers=[
            "Élève",
            "Matricule",
            "Classe",
            "État",
            {"label": "Dû", "align": "right"},
            {"label": "Entré", "align": "right"},
            {"label": "Reste", "align": "right"},
        ],
        rows=_lignes(ledger),
        theme=theme,
        empty_message="Aucune inscription ne porte ce frais sur ce périmètre.",
        col_widths=_COL_WIDTHS,
    )

    signatures = ui.signature_block(
        roles=[{"role": "Le Comptable"}, {"role": "La Direction"}],
        theme=theme,
    )

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="12mm")}{
        _STYLES
    }</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type=f"POINT SUR : {ledger.category_name.upper()}",
            doc_subtitle=_periode(ledger),
        )
    }
        {ui.meta_banner(meta_gauche, meta_droite, theme=theme)}
        {_avertissement_cloisonnement(ledger)}
        {
        ui.amount_box(
            format_xof(ledger.total_en_argent),
            theme=theme,
            label=f"Entré en argent sur la période — {ledger.eleves_en_argent} élèves",
            currency="XOF",
        )
    }
        {_note_depots(ledger)}
        {_reste_du(ledger)}
        {detail}
        {signatures}
        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note=(
                "Document limité à votre caisse — les impayés n'y figurent pas."
                if not ledger.consolide
                else "À conserver pour la comptabilité de l'établissement."
            ),
        )
    }
        </div>
    </body>
    </html>
    """


def _reste_du(ledger: CategoryLedger) -> str:
    """Ce qui reste dû, et le fait que la période n'y change rien."""
    if ledger.total_restant_du is None:
        return ""
    return (
        '<div class="muted text-center" style="font-size:9.5px; margin:-6px 0 12px;">'
        f"Reste à payer aujourd'hui : <strong>{ui.esc(format_xof(ledger.total_restant_du))} XOF</strong>"
        f" · {ledger.eleves_restant_du} élèves. "
        "Un état, pas un événement : il ne dépend pas de la période choisie."
        "</div>"
    )


def _maintenant() -> str:
    from datetime import datetime

    return datetime.now().strftime("%d/%m/%Y %H:%M")


def generate_fee_category_ledger_pdf(
    ledger: CategoryLedger, school_settings: dict[str, Any]
) -> bytes:
    """Rend le document en PDF."""
    return HTML(string=render_fee_category_ledger_html(ledger, school_settings)).write_pdf()
