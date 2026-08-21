"""Le reçu sort en deux exemplaires identiques sur une seule A4.

La caisse imprime une feuille et la coupe en deux. Deux choses peuvent casser
sans bruit et ne se voient qu'à l'impression : le document déborde sur une
seconde page, et la coupe n'a plus de sens ; ou bien les deux moitiés
divergent, et la famille repart avec un montant que le classeur ne confirme
pas.

Les tests appellent les fonctions et lisent ce qu'elles produisent. Aucun ne
regarde le code source : un test qui inspecte l'implémentation valide la façon
d'écrire, pas le document qui sort de l'imprimante.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services.pdf._helpers import format_xof
from app.services.pdf._receipt_parts import (
    MAX_FEE_LINES,
    money,
    payment_method_display,
)
from app.services.pdf.receipt import COPY_FAMILY, COPY_SCHOOL, build_receipt_html

SCHOOL = {
    "school_name": "Collège Moderne de Bouaké",
    "ministry_code": "0512-CM-BKE",
    "address": "Quartier Air France, BP 1245 Bouaké",
    "phone": "+225 27 31 63 41 08",
    "email": "secretariat@cm-bouake.ci",
}


def _line(name: str, due: str, paid: str) -> dict:
    return {
        "name": name,
        "due": Decimal(due),
        "paid": Decimal(paid),
        "remaining": max(Decimal(due) - Decimal(paid), Decimal("0")),
        "status": "partial",
    }


def _situation(lines: list[dict]) -> dict:
    return {
        "lines": lines,
        "total_due": sum((line["due"] for line in lines), Decimal("0")),
        "total_paid": sum((line["paid"] for line in lines), Decimal("0")),
        "total_remaining": sum((line["remaining"] for line in lines), Decimal("0")),
    }


SIX_FRAIS = [
    _line("Inscription", "37000", "37000"),
    _line("Scolarité 1er trimestre", "55000", "13000"),
    _line("Scolarité 2e trimestre", "55000", "0"),
    _line("Scolarité 3e trimestre", "53000", "0"),
    _line("COGES", "10000", "0"),
    _line("Tenue scolaire", "15000", "0"),
]


def _payment(**overrides) -> dict:
    data = {
        "payment_id": 4187,
        "amount": Decimal("13000"),
        "method": "cash",
        "reference": "CAISSE-2026-0417",
        "status": "completed",
        "notes": None,
        "student_name": "Traoré Aminata (MAT-2026-0142)",
        "class_name": "6ème B",
        "academic_year_name": "2025-2026",
        "fee_description": "Scolarité 1er trimestre",
        "created_at": datetime(2026, 8, 21, 10, 42),
        "received_by_name": "sophie.yao",
        "situation": _situation(SIX_FRAIS),
        "schedule": {
            "is_late": False,
            "late_amount": Decimal("0"),
            "next_due_date": date(2026, 11, 30),
            "next_due_amount": Decimal("42000"),
        },
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Les deux exemplaires
# ---------------------------------------------------------------------------


def test_la_page_porte_deux_exemplaires_distingues():
    html = build_receipt_html(_payment(), SCHOOL)
    assert html.count(COPY_FAMILY) == 1
    assert html.count(COPY_SCHOOL) == 1


def test_les_deux_moities_portent_le_meme_montant_et_la_meme_reference():
    html = build_receipt_html(_payment(), SCHOOL)
    # Le montant du jour, le numéro de versement et la référence du document
    # apparaissent une fois par exemplaire, aux mêmes valeurs.
    assert html.count(f'rc-amount-value">{money(Decimal("13000"))}') == 2
    assert html.count("N° 4187") == 2
    assert html.count("REC-2026-4187") == 2


def test_une_moitie_se_suffit_a_elle_meme():
    """Chaque exemplaire porte tout ce qu'une famille doit y trouver."""
    html = build_receipt_html(_payment(), SCHOOL)
    for attendu in (
        "Traoré Aminata (MAT-2026-0142)",
        "Montant versé ce jour",
        "Situation financière de l",
        "Reste à payer",
        "Le Caissier",
        "Le Parent ou Tuteur",
    ):
        assert html.count(attendu) == 2, attendu


def test_le_trait_de_coupe_porte_sa_mention():
    html = build_receipt_html(_payment(), SCHOOL)
    assert html.count("Découper ici") == 1
    assert html.count('class="rc-cut"') == 1


# ---------------------------------------------------------------------------
# La situation financière
# ---------------------------------------------------------------------------


def test_la_situation_reprend_les_montants_qui_lui_sont_donnes():
    """Le reçu affiche la situation telle quelle, il ne la recalcule pas."""
    situation = _situation(SIX_FRAIS)
    html = build_receipt_html(_payment(situation=situation), SCHOOL)

    assert situation["total_due"] == Decimal("225000")
    assert situation["total_paid"] == Decimal("50000")
    assert situation["total_remaining"] == Decimal("175000")

    assert html.count(money(situation["total_due"])) == 2
    assert html.count(money(situation["total_paid"])) == 2
    assert html.count(money(situation["total_remaining"])) == 2


def test_chaque_frais_a_sa_ligne_avec_du_verse_reste():
    html = build_receipt_html(_payment(), SCHOOL)
    for frais in SIX_FRAIS:
        assert html.count(frais["name"]) >= 2
    # Scolarité 1er trimestre : 55 000 dus, 13 000 versés, 42 000 restants.
    assert html.count(format_xof(Decimal("42000"))) >= 2


def test_le_versement_du_jour_se_distingue_du_cumul():
    """Le montant du jour est annoncé comme tel, à part du total versé."""
    html = build_receipt_html(_payment(), SCHOOL)
    assert "Montant versé ce jour" in html
    assert "Déjà versé" in html
    assert "versement du jour compris" in html


def test_un_eleve_sans_autre_versement_donne_un_recu_lisible():
    """Premier versement de l'année : le tableau montre le dû, pas du vide."""
    lignes = [
        _line("Inscription", "37000", "37000"),
        _line("Scolarité 1er trimestre", "55000", "0"),
    ]
    html = build_receipt_html(
        _payment(amount=Decimal("37000"), situation=_situation(lignes)),
        SCHOOL,
    )
    assert "Aucun frais" not in html
    assert html.count("Inscription") >= 2
    assert html.count(money(Decimal("55000"))) >= 2


def test_une_inscription_sans_frais_annonce_le_vide_au_lieu_de_le_taire():
    vide = {
        "lines": [],
        "total_due": Decimal("0"),
        "total_paid": Decimal("0"),
        "total_remaining": Decimal("0"),
    }
    html = build_receipt_html(_payment(situation=vide), SCHOOL)
    assert html.count("Aucun frais n'est encore inscrit") == 2
    assert html.count(money(Decimal("0"))) >= 2


def test_au_dela_de_six_frais_le_reste_est_regroupe_sans_etre_perdu():
    """Quinze versements n'allongent pas le reçu : les frais le font."""
    lignes = SIX_FRAIS + [
        _line("Cantine annuelle", "90000", "60000"),
        _line("Transport scolaire", "75000", "45000"),
        _line("Assurance scolaire", "5000", "5000"),
    ]
    situation = _situation(lignes)
    html = build_receipt_html(_payment(situation=situation), SCHOOL)

    assert html.count("Autres frais (3)") == 2
    assert "Cantine annuelle" not in html
    # Regroupés, mais comptés : le total reste celui des neuf frais.
    assert html.count(money(situation["total_remaining"])) == 2


@pytest.mark.parametrize("nombre", [1, MAX_FEE_LINES, MAX_FEE_LINES + 5])
def test_le_tableau_ne_depasse_jamais_sa_hauteur_de_lignes(nombre: int):
    lignes = [_line(f"Frais {i}", "10000", "2500") for i in range(nombre)]
    html = build_receipt_html(_payment(situation=_situation(lignes)), SCHOOL)
    moitie = html.split('class="rc-cut"')[0]
    # Une cellule « reste » par ligne de frais, plus celle du total :
    # le tableau ne grandit pas au-delà de sa hauteur prévue.
    assert moitie.count('class="rc-rest"') <= MAX_FEE_LINES + 2


# ---------------------------------------------------------------------------
# Échéancier et moyen de paiement
# ---------------------------------------------------------------------------


def test_le_retard_prime_sur_la_prochaine_echeance():
    html = build_receipt_html(
        _payment(
            schedule={
                "is_late": True,
                "late_amount": Decimal("22000"),
                "next_due_date": date(2026, 9, 15),
                "next_due_amount": Decimal("30000"),
            }
        ),
        SCHOOL,
    )
    assert html.count(f"retard de {money(Decimal('22000'))}") == 2
    assert "Prochaine échéance" not in html


def test_sans_echeancier_configure_la_ligne_disparait():
    html = build_receipt_html(_payment(schedule={}), SCHOOL)
    assert "Prochaine échéance" not in html
    assert "retard de" not in html
    # Le reste du document tient sans elle.
    assert html.count("Reste à payer") == 2


@pytest.mark.parametrize(
    ("cle", "attendu"),
    [
        ("cash", "Espèces"),
        ("bank_transfer", "Virement bancaire"),
        # Moyens ajoutés après coup : affichés lisiblement, pas « inconnu ».
        ("orange_money", "Orange Money"),
        ("wave", "Wave"),
        ("moov_money", "Moov Money"),
        ("un_moyen_pas_encore_libelle", "Un Moyen Pas Encore Libelle"),
    ],
)
def test_le_moyen_de_paiement_n_est_pas_fige_dans_une_liste(cle: str, attendu: str):
    assert payment_method_display(cle) == attendu
    html = build_receipt_html(_payment(method=cle), SCHOOL)
    assert html.count(attendu) == 2


# ---------------------------------------------------------------------------
# Format des montants
# ---------------------------------------------------------------------------


def test_les_montants_s_ecrivent_a_l_ivoirienne():
    # Séparateur de milliers insécable : « 1 250 000 » ne se coupe pas en
    # fin de ligne dans une cellule étroite.
    assert money(Decimal("1250000")) == "1 250 000 FCFA"
    assert money(Decimal("13000")) == "13 000 FCFA"
    assert money(Decimal("0")) == "0 FCFA"


def test_un_champ_libre_trop_long_ne_pousse_pas_le_pied_hors_de_la_moitie():
    """Une note de caisse bavarde est bornée avant d'entrer dans la maquette."""
    bavard = "Versement effectué par le tuteur légal pour le compte des trois " * 6
    html = build_receipt_html(_payment(notes=bavard), SCHOOL)
    assert bavard.strip() not in html
    assert html.count("…") >= 2
    # Le pied survit dans les deux exemplaires.
    assert html.count("REC-2026-4187") == 2
