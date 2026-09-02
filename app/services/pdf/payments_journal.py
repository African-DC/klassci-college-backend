"""Journal des versements — document officiel de l'établissement.

Même gabarit que le bulletin ou le bordereau journalier : bandeau République,
en-tête à l'identité de l'école, couleurs et logo tirés des paramètres du
tenant, pied de page institutionnel. Ce n'est pas de la décoration : ce
document sort de l'école pour aller chez le comptable ou au contrôle, et un
tableau blanc sans en-tête n'est pas une pièce, c'est un brouillon.

Deux colonnes portent la valeur du document. « Encaissé par », qui transforme
une liste de sommes en chaîne de responsabilité. Et « État », sans laquelle un
versement annulé se lirait comme un versement reçu — il figure au détail parce
qu'il s'est passé quelque chose, mais son montant n'entre dans aucun total.
"""

from __future__ import annotations

from typing import Any

from app.services.payments.journal_data import PaymentsJournal
from app.services.payments.journal_labels import fee_cell
from app.services.pdf import components as ui
from app.services.pdf._helpers import format_xof
from app.services.pdf.theme import PDFTheme, method_label, status_label

_DETAIL_COL_WIDTHS = ["6%", "10%", "19%", "13%", "11%", "10%", "13%", "8%", "10%"]

#: Réglages propres au journal, qui est le seul document du lot à pouvoir
#: courir sur vingt pages.
_JOURNAL_STYLES = """
<style>
    /* L'en-tête du tableau se répète : une page de montants sans nom de
       colonne ne se relit pas, et un journal de caisse se relit toujours. */
    .pdf-table thead { display: table-header-group; }
    .pdf-table tr { break-inside: avoid; }
    /* Un titre de section seul en bas de page annonce un tableau qui n'est
       pas là. */
    .pdf-section-title { break-after: avoid; }
</style>
"""


def _detail_rows(journal: PaymentsJournal) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for line in journal.lines:
        eleve = line.student_name
        if line.student_matricule:
            eleve = f"{eleve} · {line.student_matricule}"
        rows.append(
            [
                f"#{line.id}",
                {"value": line.created_at.strftime("%d/%m %H:%M"), "type": "muted"},
                eleve,
                {"value": fee_cell(line.fee_shares), "type": "muted-lines"},
                method_label(line.method),
                {"value": line.reference or "—", "type": "muted"},
                line.cashier,
                {"value": line.status, "type": "pill"},
                {"value": format_xof(line.amount), "type": "num-emphasis"},
            ]
        )
    return rows


def _group_rows(groups: list[Any], *, labeller: Any) -> list[list[Any]]:
    return [
        [
            labeller(group.key),
            {"value": str(group.count), "type": "num"},
            {"value": format_xof(group.total), "type": "num-emphasis"},
        ]
        for group in groups
    ]


def _status_counts_line(journal: PaymentsJournal) -> str:
    """Le décompte par état, chaque état sous son propre nom.

    Aucun repli sur « autres » : un état inconnu de cette version s'imprime
    tel quel, ce qui se remarque, au lieu d'être fondu dans un chiffre que
    personne ne saurait rouvrir.
    """
    # « État : nombre » plutôt que « nombre états » : l'accord en nombre des
    # libellés français n'est pas régulier (« en attente » reste invariable),
    # et un document officiel ne peut pas se permettre « 4 en attentes ».
    pieces = [
        f"{status_label(status)} : {count}"
        for status, count in sorted(journal.counts_by_status.items())
        if count
    ]
    if not pieces:
        return ""
    return (
        '<div class="muted text-center" style="font-size:9px; margin:-8px 0 12px;">'
        + " · ".join(ui.esc(piece) for piece in pieces)
        + "</div>"
    )


def _notice(journal: PaymentsJournal) -> str:
    """Avertit quand le document ne couvre pas tout ce que le filtre a trouvé.

    Un document tronqué sans le dire est pire qu'un document absent : on le
    signe en croyant qu'il est complet.
    """
    if journal.truncated_from is None:
        return ""
    return (
        '<div style="border-left:3px solid var(--warn); background:var(--soft-bg);'
        ' padding:8px 12px; margin:10px 0; font-size:9.5px;">'
        f"Ce document ne présente que les {len(journal.lines)} premiers versements "
        f"sur les {journal.truncated_from} retenus par le filtre. "
        "Resserrez la période pour obtenir un document complet."
        "</div>"
    )


def render_payments_journal_html(journal: PaymentsJournal, school_settings: dict[str, Any]) -> str:
    """Compose le document, sans le convertir en PDF.

    Séparé de la conversion pour que la composition — l'en-tête de
    l'établissement, les colonnes, les totaux — se vérifie sans dépendre de la
    présence des bibliothèques natives de rendu.
    """
    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    meta_left = f"<strong>Périmètre :</strong> {ui.esc(journal.scope_label)}"
    if journal.filters_label:
        meta_left += f'<br/><span class="muted">{ui.esc(journal.filters_label)}</span>'
    meta_right = f"Édité le {ui.esc(journal.issued_at.strftime('%d/%m/%Y %H:%M'))}"

    par_moyen = ui.section_title("Récapitulatif par moyen de paiement", theme=theme)
    par_moyen += ui.premium_table(
        headers=[
            "Moyen de paiement",
            {"label": "Versements", "align": "right"},
            {"label": "Total XOF", "align": "right"},
        ],
        rows=_group_rows(journal.by_method, labeller=method_label),
        theme=theme,
        empty_message="Aucun versement validé sur cette sélection.",
        col_widths=["50%", "22%", "28%"],
    )

    par_caissier = ""
    if journal.by_cashier:
        par_caissier = ui.section_title("Récapitulatif par caissier", theme=theme)
        par_caissier += ui.premium_table(
            headers=[
                "Encaissé par",
                {"label": "Versements", "align": "right"},
                {"label": "Total XOF", "align": "right"},
            ],
            rows=_group_rows(journal.by_cashier, labeller=str),
            theme=theme,
            col_widths=["50%", "22%", "28%"],
        )

    detail = ui.section_title("Détail des versements", theme=theme) + ui.premium_table(
        headers=[
            "N°",
            "Date",
            "Élève",
            "Frais",
            "Moyen",
            "Référence",
            "Encaissé par",
            "État",
            {"label": "Montant", "align": "right"},
        ],
        rows=_detail_rows(journal),
        theme=theme,
        empty_message="Aucun versement ne correspond à cette sélection.",
        col_widths=_DETAIL_COL_WIDTHS,
    )

    signatures = ui.signature_block(
        roles=[{"role": "Le Caissier"}, {"role": "La Comptabilité"}],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4 landscape", margin="12mm")}{
        _JOURNAL_STYLES
    }</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="JOURNAL DES VERSEMENTS",
            doc_subtitle=journal.period_label,
        )
    }
        {ui.meta_banner(meta_left, meta_right, theme=theme)}
        {
        ui.amount_box(
            format_xof(journal.total_encaisse),
            theme=theme,
            label="Total encaissé (versements validés)",
            currency="XOF",
        )
    }
        {_status_counts_line(journal)}
        {_notice(journal)}
        {par_moyen}
        {par_caissier}
        {detail}
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

    return html


def generate_payments_journal_pdf(
    journal: PaymentsJournal, school_settings: dict[str, Any]
) -> bytes:
    """Génère le journal des versements au gabarit officiel de l'établissement."""
    from weasyprint import HTML  # lazy import — GTK n'est chargé qu'ici

    return HTML(string=render_payments_journal_html(journal, school_settings)).write_pdf()
