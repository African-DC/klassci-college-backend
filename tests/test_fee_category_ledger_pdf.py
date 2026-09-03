"""Le PDF doit dire ce qu'il ne dit pas.

Ce document part chez un prestataire pour justifier un virement. Deux mentions
y portent toute la valeur, et un rendu qui les perdrait serait pire qu'un rendu
absent : on signerait un total en croyant qu'il couvre l'ecole.

La composition est testee sans WeasyPrint — on verifie le HTML, pas le PDF.
C'est ce qui permet de la tenir sans les bibliotheques natives, et c'est aussi
ce que le journal des versements fait deja.
"""

from decimal import Decimal

from app.services.fee_category_ledger import CategoryLedger, LigneEleve
from app.services.pdf.fee_category_ledger import render_fee_category_ledger_html

ECOLE = {"school_name": "College Rostan", "primary_color": "#0F3F8C"}


def _ledger(*, consolide: bool, accepts_in_kind: bool = True) -> CategoryLedger:
    return CategoryLedger(
        category_id=1,
        category_name="Paquet de rames",
        accepts_in_kind=accepts_in_kind,
        class_name="Toutes les classes",
        date_from=None,
        date_to=None,
        consolide=consolide,
        eleves_en_argent=2,
        total_en_argent=Decimal("6000"),
        depots_en_nature=3,
        eleves_restant_du=1 if consolide else None,
        total_restant_du=Decimal("3000") if consolide else None,
        lignes=(
            LigneEleve(
                enrollment_id=1,
                student_id=1,
                first_name="Aminata",
                last_name="Diallo",
                student_matricule="M001",
                class_name="6e A",
                status="pending",
                due=Decimal("3000"),
                paid=Decimal("0"),
                remaining=Decimal("3000") if consolide else None,
                deposited_at=None,
            ),
        ),
    )


def test_le_document_avertit_quand_il_ne_couvre_qu_une_caisse() -> None:
    """Sans cette ligne, un etat de guichet se lit comme le compte de l'ecole."""
    html = render_fee_category_ledger_html(_ledger(consolide=False), ECOLE)

    assert "ne couvre que votre caisse" in html
    # Repete en pied, pour qui feuillette par la fin.
    assert "les impayés n'y figurent pas" in html


def test_un_document_consolide_ne_porte_pas_cet_avertissement() -> None:
    html = render_fee_category_ledger_html(_ledger(consolide=True), ECOLE)

    assert "ne couvre que votre caisse" not in html


def test_le_reste_du_dit_que_la_periode_n_y_change_rien() -> None:
    """Un etat, pas un evenement : le borner n'aurait aucun sens."""
    html = render_fee_category_ledger_html(_ledger(consolide=True), ECOLE)

    assert "ne dépend pas de la période choisie" in html


def test_sans_le_droit_global_aucun_reste_n_est_annonce() -> None:
    html = render_fee_category_ledger_html(_ledger(consolide=False), ECOLE)

    assert "Reste à payer aujourd'hui" not in html


def test_le_document_ne_promet_pas_des_paquets() -> None:
    """La base enregistre un depot par ligne de frais, jamais une quantite.

    Parler de paquets ferait commander une livraison sur un decompte que la
    base ne tient pas.
    """
    html = render_fee_category_ledger_html(_ledger(consolide=True), ECOLE)

    assert "jamais une quantité d'articles" in html
    assert "paquets" not in html.lower().replace("paquet de rames", "")


def test_une_categorie_sans_depot_ne_parle_pas_de_depots() -> None:
    html = render_fee_category_ledger_html(_ledger(consolide=True, accepts_in_kind=False), ECOLE)

    assert "Dépôts en nature" not in html


def test_le_nom_de_la_categorie_titre_le_document() -> None:
    html = render_fee_category_ledger_html(_ledger(consolide=True), ECOLE)

    assert "PAQUET DE RAMES" in html


def test_la_pastille_porte_la_cle_et_non_le_mot() -> None:
    """Sinon toute la colonne « Etat » sort sans couleur, et personne ne le voit.

    `status_pill` fabrique sa classe CSS a partir de la valeur recue :
    `pdf-pill-paid`, `-partial`, `-pending`... Lui passer « Solde » produisait
    `pdf-pill-solde`, qui n'est definie nulle part. Le document restait juste
    dans ses mots et muet dans ses couleurs — le genre de defaut qu'un test de
    presence de texte ne voit pas, parce que le texte, lui, etait bien la.
    """
    html = render_fee_category_ledger_html(_ledger(consolide=True), ECOLE)

    # La classe vient de la cle...
    assert "pdf-pill-pending" in html
    # ...et le mot affiche reste celui du document, pas celui de la table
    # partagee : sur un frais on dit « Du », pas « En attente ».
    assert ">Dû<" in html
    # Aucune classe fabriquee a partir d'un libelle francais.
    for mot in ("pdf-pill-du", "pdf-pill-solde", "pdf-pill-soldé", "pdf-pill-dû"):
        assert mot not in html


def test_le_compte_des_depots_est_celui_de_la_caisse_lue() -> None:
    """Le nombre affiche doit etre celui que le ledger porte, sans reinterpretation.

    Le cloisonnement se decide en amont, dans `load_category_ledger` : ce test
    tient seulement la promesse du composeur, qui est de ne pas inventer un
    chiffre a la place de celui qu'on lui donne.
    """
    html = render_fee_category_ledger_html(_ledger(consolide=False), ECOLE)

    assert "<strong>3</strong>" in html
    assert "jamais une quantité d'articles" in html
