"""Le point d'une catégorie de frais, au format classeur.

C'est le document que le comptable « tire ». Il sort de l'école : il part chez
un prestataire pour justifier un versement, ou sur un bureau pour préparer des
relances. Il doit donc dire de quoi il parle sans qu'on ait à le demander — la
catégorie, la période, le périmètre — et surtout **dire ce qu'il ne dit pas**.

Un classeur qui tairait qu'il ne couvre qu'une seule caisse serait pris pour le
compte de l'école entière. C'est la première ligne de son en-tête.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.services.exports._workbook_branding import (
    set_widths,
    setup_printing,
    style_table_header,
    style_total_row,
    write_header,
)
from app.services.fee_category_ledger import CategoryLedger

_MONEY = '#,##0" F"'

#: Le mot de chaque etat, du point de vue de qui lit le document.
_ETAT: dict[str, str] = {
    "paid": "Soldé",
    "partial": "Partiel",
    "pending": "Dû",
    "in_kind": "Déposé en nature",
    "waived": "Exonéré",
}

_COLONNES = [
    "Élève",
    "Matricule",
    "Classe",
    "État",
    "Dû (XOF)",
    "Entré sur la période (XOF)",
    "Reste à payer (XOF)",
    "Déposé le",
]
_LARGEURS = [28, 16, 14, 18, 14, 24, 18, 14]


def _periode(ledger: CategoryLedger) -> str:
    if ledger.date_from and ledger.date_to:
        return f"Du {ledger.date_from:%d/%m/%Y} au {ledger.date_to:%d/%m/%Y}"
    if ledger.date_from:
        return f"À partir du {ledger.date_from:%d/%m/%Y}"
    if ledger.date_to:
        return f"Jusqu'au {ledger.date_to:%d/%m/%Y}"
    return "Depuis le début de l'année"


def _meta(ledger: CategoryLedger) -> list[str]:
    lignes = [f"Périmètre : {ledger.class_name}"]

    if not ledger.consolide:
        # La ligne la plus importante de l'en-tete : sans elle, un document de
        # guichet se lit comme le compte de l'ecole entiere.
        lignes.append(
            "ATTENTION : ce document ne couvre que votre caisse. "
            "Il ne dit rien de ce qui a été encaissé ailleurs, "
            "et ne comporte donc aucun reste à payer."
        )

    lignes.append(
        f"Entré en argent sur la période : {ledger.eleves_en_argent} élèves, "
        f"{ledger.total_en_argent:,.0f} F".replace(",", " ")
    )
    if ledger.accepts_in_kind:
        lignes.append(
            f"Déposé en nature sur la période : {ledger.depots_en_nature} dépôts. "
            "Un dépôt vaut une ligne de frais remise, jamais une quantité d'articles."
        )
    if ledger.consolide and ledger.total_restant_du is not None:
        lignes.append(
            f"Reste à payer aujourd'hui : {ledger.eleves_restant_du} élèves, "
            f"{ledger.total_restant_du:,.0f} F. "
            "Un état, pas un événement : il ne dépend pas de la période choisie.".replace(",", " ")
        )
    return lignes


def _ecrire(ws: Worksheet, ledger: CategoryLedger, school: dict[str, Any]) -> None:
    header_row = write_header(
        ws,
        school,
        title=f"Point sur : {ledger.category_name}",
        subtitle=_periode(ledger),
        meta_lines=_meta(ledger),
        width=len(_COLONNES),
    )
    set_widths(ws, _LARGEURS)

    for index, label in enumerate(_COLONNES, 1):
        ws.cell(row=header_row, column=index, value=label)
    style_table_header(ws, header_row, len(_COLONNES), school)

    row = header_row
    for ligne in ledger.lignes:
        row += 1
        ws.cell(row=row, column=1, value=f"{ligne.last_name} {ligne.first_name}".strip())
        ws.cell(row=row, column=2, value=ligne.student_matricule or "—")
        ws.cell(row=row, column=3, value=ligne.class_name or "—")
        ws.cell(row=row, column=4, value=_ETAT.get(ligne.status, ligne.status))
        for colonne, valeur in ((5, ligne.due), (6, ligne.paid)):
            cellule = ws.cell(row=row, column=colonne, value=float(valeur))
            cellule.number_format = _MONEY
        # Le reste du est absent, pas nul, quand on ne lit qu'une caisse : un
        # zero se lirait comme un solde.
        reste = ws.cell(
            row=row,
            column=7,
            value=float(ligne.remaining) if ligne.remaining is not None else "—",
        )
        if ligne.remaining is not None:
            reste.number_format = _MONEY
        ws.cell(
            row=row,
            column=8,
            value=ligne.deposited_at.strftime("%d/%m/%Y") if ligne.deposited_at else "—",
        )

    total_row = row + 1
    ws.cell(row=total_row, column=1, value="Total entré sur la période")
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=5)
    total = ws.cell(row=total_row, column=6, value=float(ledger.total_en_argent))
    total.number_format = _MONEY
    if ledger.total_restant_du is not None:
        reste_total = ws.cell(row=total_row, column=7, value=float(ledger.total_restant_du))
        reste_total.number_format = _MONEY
    style_total_row(ws, total_row, len(_COLONNES), school)

    if not ledger.consolide:
        # Repete en pied de tableau : un lecteur qui arrive par la fin doit le
        # voir aussi.
        note = ws.cell(
            row=total_row + 2,
            column=1,
            value="Document limité à votre caisse — les impayés ne peuvent pas y figurer.",
        )
        note.font = Font(italic=True, size=9)

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    setup_printing(ws, header_row=header_row)


def generate_fee_category_ledger_xlsx(
    ledger: CategoryLedger, school_settings: dict[str, Any]
) -> bytes:
    """Génère le classeur du point de catégorie aux couleurs de l'école."""
    wb = Workbook()
    feuille = wb.active
    feuille.title = "Point"
    _ecrire(feuille, ledger, school_settings)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
