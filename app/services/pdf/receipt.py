"""Reçu de versement — une A4 portant deux exemplaires identiques.

La caisse imprime une feuille et la coupe en deux : un exemplaire part avec la
famille, l'autre reste au classeur. C'est la pratique du guichet, et elle
économise une feuille sur deux.

Les deux moitiés sont composées par le même code, à partir des mêmes données :
elles portent donc le même montant, la même référence et la même situation
financière. Seule la mention d'exemplaire les distingue, pour qu'un même
versement ne soit pas classé deux fois.

Le document ne porte pas de sceau numérique KLASSCI — il n'en a jamais porté :
son identité est le numéro du versement, qui vient de la caisse. Voir la note
de `build_receipt_html` sur ce choix.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import _receipt_parts as parts
from app.services.pdf._receipt_styles import receipt_styles
from app.services.pdf.theme import PDFTheme

COPY_FAMILY = "Exemplaire famille"
COPY_SCHOOL = "Exemplaire établissement"


def _document_reference(payment_data: dict[str, Any]) -> str:
    """Référence du document, identique sur les deux moitiés.

    Un versement, une référence. Numéroter les exemplaires séparément
    reviendrait à faire exister deux pièces comptables là où la caisse n'a
    encaissé qu'une fois.
    """
    payment_id = payment_data.get("payment_id")
    created_at = payment_data.get("created_at")
    year = created_at.year if isinstance(created_at, datetime) else datetime.now().year
    return f"REC-{year}-{payment_id}" if payment_id else ""


def _half_html(data: dict[str, Any], school: dict[str, Any], *, copy_label: str) -> str:
    """Un exemplaire complet et autonome, sur une moitié de page."""
    created_at = data.get("created_at")
    when = created_at.strftime("%d/%m/%Y") if isinstance(created_at, datetime) else ""
    doc_number = " · ".join(
        p for p in (f"N° {data.get('payment_id', '')}".strip(), when) if p.strip()
    )
    return f"""
    <div class="rc-half">
        {parts.header_html(school, doc_number=doc_number, copy_label=copy_label)}
        <table class="rc-cols"><tr>
            <td class="rc-col-left">{parts.payment_column_html(data)}</td>
            <td class="rc-col-right">{parts.situation_column_html(data)}</td>
        </tr></table>
        {parts.key_figures_html(data)}
        <div class="rc-bottom">{parts.footer_html(data, school)}</div>
    </div>
    """


def build_receipt_html(payment_data: dict[str, Any], school_settings: dict[str, Any]) -> str:
    """Compose le HTML de l'A4 deux exemplaires.

    Séparé du rendu pour être vérifiable sans WeasyPrint : les tests peuvent
    compter les pages, comparer les deux moitiés et relire la situation
    financière sans dépendre des bibliothèques natives d'impression.

    Sur le sceau : le reçu n'entre pas au registre des documents vérifiables,
    contrairement au bulletin ou au certificat. C'est délibéré. Un reçu se
    réimprime autant de fois que la famille le demande, et chaque impression
    créerait une inscription au registre pour un seul encaissement. La pièce
    opposable reste le versement en base, dont le numéro figure ici.
    """
    school = school_settings or {}
    theme = PDFTheme.from_school(school)
    data = dict(payment_data or {})
    data.setdefault("document_reference", _document_reference(data))

    return f"""<!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{receipt_styles(theme)}</head>
    <body>
        {_half_html(data, school, copy_label=COPY_FAMILY)}
        <div class="rc-cut"><span class="rc-cut-label">Découper ici</span></div>
        {_half_html(data, school, copy_label=COPY_SCHOOL)}
    </body>
    </html>
    """


def generate_receipt_pdf(payment_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Rend le reçu en PDF — une A4 portrait, deux exemplaires à découper.

    payment_data : payment_id, amount, method, reference, status, notes,
        student_name, class_name, academic_year_name, fee_description,
        created_at, received_by_name, situation, schedule.
    school_settings : school_name, ministry_code, address, phone, email,
        logo_url, primary_color, accent_color, website.
    """
    from weasyprint import HTML  # lazy import — dépendances natives GTK

    return HTML(string=build_receipt_html(payment_data, school_settings)).write_pdf()
