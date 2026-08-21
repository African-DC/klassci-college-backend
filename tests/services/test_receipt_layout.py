"""Le reçu tient sur une seule A4, quelle que soit la longueur des données.

Une deuxième page ruine la découpe : la moitié « établissement » part sur une
feuille séparée, et la caisse se retrouve avec deux feuilles à agrafer au lieu
d'une à couper. C'est invisible au HTML, cela ne se voit qu'à la mise en page,
donc ces tests rendent réellement le document.

WeasyPrint dépend de bibliothèques natives (Pango, Cairo). Là où elles manquent,
le module entier se saute plutôt que de faire échouer la suite pour une raison
d'environnement : les assertions de contenu vivent dans
`test_receipt_duplicate`, qui ne rend rien.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services.pdf._receipt_styles import HALF_HEIGHT_MM
from app.services.pdf.receipt import build_receipt_html, generate_receipt_pdf

try:  # pragma: no cover - dépend de l'environnement d'exécution
    from weasyprint import HTML
except OSError as exc:  # pragma: no cover
    pytest.skip(f"WeasyPrint indisponible : {exc}", allow_module_level=True)

MM_PER_PX = 25.4 / 96
A4_WIDTH_MM, A4_HEIGHT_MM = 210.0, 297.0

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
        "total_due": sum((x["due"] for x in lines), Decimal("0")),
        "total_paid": sum((x["paid"] for x in lines), Decimal("0")),
        "total_remaining": sum((x["remaining"] for x in lines), Decimal("0")),
    }


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
        "situation": _situation(
            [
                _line("Inscription", "37000", "37000"),
                _line("Scolarité 1er trimestre", "55000", "13000"),
                _line("Scolarité 2e trimestre", "55000", "0"),
                _line("Scolarité 3e trimestre", "53000", "0"),
                _line("COGES", "10000", "0"),
                _line("Tenue scolaire", "15000", "0"),
            ]
        ),
        "schedule": {
            "is_late": False,
            "late_amount": Decimal("0"),
            "next_due_date": date(2026, 11, 30),
            "next_due_amount": Decimal("42000"),
        },
    }
    data.update(overrides)
    return data


def _pages(data: dict, school: dict | None = None) -> list:
    return HTML(string=build_receipt_html(data, school or SCHOOL)).render().pages


# --- Situations extrêmes ----------------------------------------------------

UN_SEUL_FRAIS = _situation([_line("Inscription", "37000", "37000")])

QUINZE_VERSEMENTS = _situation(
    [
        _line("Inscription", "37000", "37000"),
        _line("Scolarité 1er trimestre", "55000", "55000"),
        _line("Scolarité 2e trimestre", "55000", "55000"),
        _line("Scolarité 3e trimestre", "53000", "31000"),
        _line("COGES", "10000", "10000"),
        _line("Tenue scolaire et sportive", "15000", "15000"),
        _line("Cantine annuelle", "90000", "60000"),
        _line("Transport scolaire", "75000", "45000"),
        _line("Assurance scolaire", "5000", "5000"),
        _line("Bibliothèque et fournitures", "12000", "12000"),
        _line("Activités parascolaires", "8000", "0"),
        _line("Frais d'examen blanc", "6000", "0"),
    ]
)

AUCUN_FRAIS = {
    "lines": [],
    "total_due": Decimal("0"),
    "total_paid": Decimal("0"),
    "total_remaining": Decimal("0"),
}

DEBORDANT = _payment(
    amount=Decimal("1250000"),
    method="mtn_momo",
    reference="MTNCI-2026-08-21-0000889341276-XZ",
    notes="Versement effectué par le tuteur légal pour le compte des trois enfants " * 4,
    student_name="N'Dri Kouakou Marie-Chantal Adjoua Épouse Kouassi (MAT-2026-000142-YAM)",
    class_name="Terminale scientifique D2 groupe 3",
    situation=QUINZE_VERSEMENTS,
    schedule={
        "is_late": True,
        "late_amount": Decimal("122500"),
        "next_due_date": date(2026, 9, 15),
        "next_due_amount": Decimal("30000"),
    },
)

ECOLE_BAVARDE = {
    "school_name": "Groupe Scolaire Privé Confessionnel Notre-Dame de l'Annonciation de Yamoussoukro",
    "ministry_code": "0912-GSPC-YAM-2026",
    "address": "Boulevard de la Paix, Quartier Habitat Extension Nord, 08 BP 2274 Yamoussoukro 08",
    "phone": "+225 27 30 64 12 88",
    "email": "direction.comptabilite@notredame-annonciation-yamoussoukro.edu.ci",
}


@pytest.mark.parametrize(
    ("nom", "data", "school"),
    [
        ("un seul versement", _payment(situation=UN_SEUL_FRAIS), SCHOOL),
        ("six frais", _payment(), SCHOOL),
        ("quinze versements", _payment(situation=QUINZE_VERSEMENTS), SCHOOL),
        ("aucun frais", _payment(situation=AUCUN_FRAIS, schedule={}), SCHOOL),
        ("tout déborde", DEBORDANT, ECOLE_BAVARDE),
    ],
)
def test_le_recu_tient_sur_une_seule_page(nom: str, data: dict, school: dict):
    pages = _pages(data, school)
    assert len(pages) == 1, f"{nom} : {len(pages)} pages, la découpe n'a plus de sens"


def test_la_page_est_une_a4_portrait():
    (page,) = _pages(_payment())
    assert round(page.width * MM_PER_PX, 1) == A4_WIDTH_MM
    assert round(page.height * MM_PER_PX, 1) == A4_HEIGHT_MM


def _bas_du_contenu(page) -> float:
    """Ordonnée du dernier trait ou texte posé, en millimètres."""

    def descend(boxes) -> float:
        bas = 0.0
        for box in boxes:
            enfants = getattr(box, "children", ()) or ()
            if enfants:
                bas = max(bas, descend(enfants))
            else:
                bas = max(bas, (box.position_y + box.height) * MM_PER_PX)
        return bas

    return descend(page._page_box.children)


def _ordonnees(page, fragment: str) -> list[float]:
    """Ordonnées, en millimètres, des textes contenant `fragment`."""

    def descend(boxes):
        for box in boxes:
            enfants = getattr(box, "children", ()) or ()
            if enfants:
                yield from descend(enfants)
            elif fragment in (getattr(box, "text", "") or ""):
                yield box.position_y * MM_PER_PX

    return sorted(descend(page._page_box.children))


@pytest.mark.parametrize(
    ("nom", "data", "school"),
    [
        ("six frais", _payment(), SCHOOL),
        ("quinze versements", _payment(situation=QUINZE_VERSEMENTS), SCHOOL),
        ("tout déborde", DEBORDANT, ECOLE_BAVARDE),
    ],
)
def test_le_second_exemplaire_ne_deborde_pas_de_la_feuille(nom: str, data: dict, school: dict):
    """Rien ne dépasse le bas de l'A4 : le second exemplaire est complet."""
    (page,) = _pages(data, school)
    assert _bas_du_contenu(page) <= A4_HEIGHT_MM, nom


def test_les_deux_exemplaires_font_la_meme_hauteur():
    """Le trait de coupe tombe au milieu : les deux moitiés sont égales."""
    assert HALF_HEIGHT_MM * 2 <= A4_HEIGHT_MM
    assert A4_HEIGHT_MM - HALF_HEIGHT_MM * 2 < 2.0


@pytest.mark.parametrize(
    ("nom", "data", "school"),
    [
        ("un seul versement", _payment(situation=UN_SEUL_FRAIS), SCHOOL),
        ("six frais", _payment(), SCHOOL),
        ("quinze versements", _payment(situation=QUINZE_VERSEMENTS), SCHOOL),
        ("tout déborde", DEBORDANT, ECOLE_BAVARDE),
    ],
)
def test_l_exemplaire_famille_est_entier_au_dessus_du_trait(nom: str, data: dict, school: dict):
    """La famille coupe au milieu et emporte un reçu complet.

    Le test qui manque le plus : le document peut tenir sur une page tout en
    laissant les signatures et la référence du premier exemplaire glisser sous
    le trait de coupe. Le ciseau les emporte alors avec la moitié du classeur,
    et la famille repart avec un reçu ni signé ni référencé.
    """
    (page,) = _pages(data, school)
    reference = data["document_reference"] if "document_reference" in data else "REC-2026-"
    for texte in ("LE CAISSIER", "LE PARENT OU TUTEUR", "RESTE À PAYER", reference):
        positions = _ordonnees(page, texte)
        assert len(positions) == 2, f"{nom} : {texte} vu {len(positions)} fois"
        assert positions[0] < HALF_HEIGHT_MM, f"{nom} : {texte} sous le trait de coupe"
        assert HALF_HEIGHT_MM <= positions[1] < A4_HEIGHT_MM, f"{nom} : {texte} hors feuille"


def test_le_rendu_produit_bien_un_pdf():
    pdf = generate_receipt_pdf(_payment(), SCHOOL)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 5_000
