"""Decor partage des tests des deux sorties du point par categorie.

Module d'appui, pas un module de test : le PDF et le classeur sortent du MEME
`CategoryLedger`, et les faire partir de deux decors construits a la main
serait le meilleur moyen de ne jamais voir qu'ils ne disent pas la meme chose.
C'est precisement le defaut qu'on vient de fermer.

Aucun rendu n'est simule ici : les deux fabriques sont appelees pour de vrai,
sans WeasyPrint pour le PDF — on verifie le HTML compose, pas le PDF.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.services.fee_category_ledger import LEDGER_MAX_ROWS, CategoryLedger, LigneEleve

ECOLE = {"school_name": "College Rostan", "primary_color": "#0F3F8C"}

#: L'instant du tirage. Il est INJECTE : le composeur ne va plus le chercher
#: lui-meme, sans quoi les deux sorties d'un meme point porteraient deux
#: heures et aucune des deux ne se testerait.
EDITION = datetime(2026, 11, 12, 16, 45)

CAISSIERE = "N'GUESSAN Marcel"
COMPTABLE = "KOUAME Adjoua"


def ligne(**remplace: Any) -> LigneEleve:
    """Une ligne d'eleve. Soldee par defaut, pour que le zero soit un vrai zero."""
    champs: dict[str, Any] = {
        "enrollment_id": 1,
        "student_id": 1,
        "first_name": "Aminata",
        "last_name": "Diallo",
        "student_matricule": "M001",
        "class_name": "6e A",
        "status": "pending",
        "due": Decimal("3000"),
        "paid": Decimal("0"),
        "remaining": Decimal("3000"),
        "deposited_at": None,
    }
    champs.update(remplace)
    return LigneEleve(**champs)


def document(
    *,
    consolide: bool,
    accepts_in_kind: bool = True,
    lignes: tuple[LigneEleve, ...] | None = None,
    **remplace: Any,
) -> CategoryLedger:
    """Le point d'une categorie, tel que `load_category_ledger` le rend.

    `consolide` commande tout ce qui se lit sur l'argent de toutes les caisses :
    sans lui, ces champs-la sont ABSENTS, jamais mis a zero.
    """
    if lignes is None:
        lignes = (ligne(remaining=Decimal("3000") if consolide else None),)
    champs: dict[str, Any] = {
        "category_id": 1,
        "category_name": "Paquet de rames",
        "accepts_in_kind": accepts_in_kind,
        "academic_year_id": 4,
        "academic_year_name": "2026-2027",
        "class_name": "Toutes les classes",
        "date_from": None,
        "date_to": None,
        "consolide": consolide,
        "scope_label": ("Toutes les caisses" if consolide else f"Ma caisse — {CAISSIERE}"),
        "cashier_name": None if consolide else CAISSIERE,
        "issued_by": COMPTABLE if consolide else CAISSIERE,
        "issued_at": EDITION,
        "effectif_perimetre": 4,
        "eleves_sans_ligne": 3,
        "eleves_en_argent": 2,
        "total_en_argent": Decimal("6000"),
        "depots_en_nature": 3,
        "eleves_restant_du": 1 if consolide else None,
        "total_restant_du": Decimal("3000") if consolide else None,
        "total_attendu": Decimal("3000") if consolide else None,
        "taux_recouvrement": 0.0 if consolide else None,
        "compteurs": {"pending": 1} if consolide else None,
        "etat_filtre": None,
        "recherche": None,
        "recherche_approchee": False,
        "total_lignes": len(lignes),
        "page": 1,
        "size": LEDGER_MAX_ROWS,
        "truncated_from": None,
        "lignes": lignes,
    }
    champs.update(remplace)
    return CategoryLedger(**champs)
