"""Le PDF doit dire ce qu'il ne dit pas, et nommer ce dont il parle.

Ce document part chez un prestataire pour justifier un virement. Trois mentions
y portent toute la valeur, et un rendu qui les perdrait serait pire qu'un rendu
absent : on signerait un total en croyant qu'il couvre l'ecole.

La composition est testee sans WeasyPrint — on verifie le HTML, pas le PDF.
C'est ce qui permet de la tenir sans les bibliotheques natives, et c'est aussi
ce que le journal des versements fait deja.

La concordance avec le classeur, elle, se mesure dans
`test_fee_category_ledger_documents.py` : elle ne se voit pas en regardant une
seule des deux sorties.
"""

from decimal import Decimal

from app.services.pdf.fee_category_ledger import render_fee_category_ledger_html
from tests.fee_category_ledger_decor import CAISSIERE, COMPTABLE, ECOLE, document, ligne


def test_le_document_avertit_quand_il_ne_couvre_qu_une_caisse() -> None:
    """Sans cette ligne, un etat de guichet se lit comme le compte de l'ecole."""
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert "ne couvre que votre caisse" in html
    # Repete en pied, pour qui feuillette par la fin.
    assert "les impayés n'y figurent pas" in html


def test_un_document_consolide_ne_porte_pas_cet_avertissement() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "ne couvre que votre caisse" not in html


def test_le_reste_du_dit_que_la_periode_n_y_change_rien() -> None:
    """Un etat, pas un evenement : le borner n'aurait aucun sens."""
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "ne dépend pas de la période choisie" in html


def test_sans_le_droit_global_aucun_reste_n_est_annonce() -> None:
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert "Reste à payer aujourd'hui" not in html


def test_le_document_ne_promet_pas_des_paquets() -> None:
    """La base enregistre un depot par ligne de frais, jamais une quantite.

    Parler de paquets ferait commander une livraison sur un decompte que la
    base ne tient pas.
    """
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "jamais une quantité d'articles" in html
    assert "paquets" not in html.lower().replace("paquet de rames", "")


def test_une_categorie_sans_depot_ne_parle_pas_de_depots() -> None:
    html = render_fee_category_ledger_html(document(consolide=True, accepts_in_kind=False), ECOLE)

    assert "Déposé en nature sur la période" not in html
    # Et pas davantage la colonne du dépôt, que le classeur portait seul.
    assert "Déposé le" not in html


def test_le_nom_de_la_categorie_titre_le_document() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "PAQUET DE RAMES" in html


def test_la_pastille_porte_la_cle_et_non_le_mot() -> None:
    """Sinon toute la colonne « Etat » sort sans couleur, et personne ne le voit.

    `status_pill` fabrique sa classe CSS a partir de la valeur recue :
    `pdf-pill-paid`, `-partial`, `-pending`... Lui passer « Solde » produisait
    `pdf-pill-solde`, qui n'est definie nulle part. Le document restait juste
    dans ses mots et muet dans ses couleurs — le genre de defaut qu'un test de
    presence de texte ne voit pas, parce que le texte, lui, etait bien la.
    """
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    # La classe vient de la cle...
    assert "pdf-pill-pending" in html
    # ...et le mot affiche reste celui du document, pas celui de la table
    # partagee des versements : sur un frais on dit « Du », pas « En attente ».
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
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert "3 dépôts" in html
    assert "jamais une quantité d'articles" in html


# ---------------------------------------------------------------------------
# Le document nomme ce dont il parle
# ---------------------------------------------------------------------------


def test_le_document_nomme_son_annee_scolaire() -> None:
    """Sans elle, deux points de deux exercices sont indiscernables sur un bureau.

    L'annee est pourtant un parametre OBLIGATOIRE de l'entree : elle etait
    connue de bout en bout, et imprimee nulle part.
    """
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "2026-2027" in html


def test_le_document_nomme_sa_caisse_et_son_porteur() -> None:
    """« Votre caisse uniquement » ne dit pas de qui est la caisse."""
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert f"Ma caisse — {CAISSIERE}" in html


def test_un_point_consolide_ne_designe_aucune_caisse_particuliere() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "Toutes les caisses" in html
    assert "Ma caisse" not in html


def test_le_document_dit_quand_il_a_ete_tire_et_par_qui() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "Édité le 12/11/2026 à 16:45" in html
    assert COMPTABLE in html


def test_l_heure_vient_du_document_et_non_de_l_horloge_du_composeur() -> None:
    """Deux compositions du meme point doivent rendre exactement le meme texte.

    Le composeur relisait `datetime.now()` : le PDF et le classeur d'un meme
    tirage portaient deux instants, et aucun des deux ne se testait.
    """
    point = document(consolide=True)

    assert render_fee_category_ledger_html(point, ECOLE) == render_fee_category_ledger_html(
        point, ECOLE
    )


def test_le_document_nomme_les_filtres_qu_il_porte() -> None:
    """Lus du filtre, jamais des donnees : une liste vide ne dit pas ce qui l'a videe."""
    html = render_fee_category_ledger_html(
        document(consolide=True, etat_filtre="impayes", recherche="kouame"), ECOLE
    )

    assert "Filtres appliqués" in html
    assert "Impayés" in html
    assert "kouame" in html


def test_un_document_sans_filtre_n_en_annonce_aucun() -> None:
    """Annoncer un filtre qui n'a pas porte ferait mentir le document."""
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "Filtres appliqués" not in html


# ---------------------------------------------------------------------------
# La signature suit le perimetre
# ---------------------------------------------------------------------------


def test_un_etat_de_guichet_est_signe_par_sa_caissiere() -> None:
    """Faire signer « La Direction » sous le point d'une caisse n'engage personne."""
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert "Le Caissier" in html
    assert "La Direction" not in html


def test_un_point_consolide_est_signe_par_la_comptabilite_et_la_direction() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "La Comptabilité" in html
    assert "La Direction" in html
    assert "Le Caissier" not in html


# ---------------------------------------------------------------------------
# Le tiret dit « on ne sait pas », jamais « zero »
# ---------------------------------------------------------------------------


def test_une_ligne_soldee_affiche_zero_et_non_un_tiret() -> None:
    """Le tiret est reserve a l'inconnu. Sur une ligne soldee, le reste vaut zero.

    Le PDF testait la faussete du montant : un eleve a jour sortait « — » ici
    et « 0 F » dans le classeur. Le meme eleve etait donc « inconnu » dans la
    piece signee et « solde » dans celle qu'on recalcule.
    """
    soldee = ligne(status="paid", paid=Decimal("3000"), remaining=Decimal("0"))
    html = render_fee_category_ledger_html(document(consolide=True, lignes=(soldee,)), ECOLE)

    assert '<td class="num">0</td>' in html


def test_la_colonne_du_reste_disparait_quand_personne_ne_peut_la_remplir() -> None:
    """Une colonne integralement remplie de tirets promet des francs qu'elle n'a pas."""
    html = render_fee_category_ledger_html(document(consolide=False), ECOLE)

    assert "Reste à payer (XOF)" not in html


# ---------------------------------------------------------------------------
# Le plafond, et sa mention
# ---------------------------------------------------------------------------


def test_un_document_tronque_le_dit() -> None:
    """Un document ampute qui se tait se signe comme s'il etait complet."""
    html = render_fee_category_ledger_html(document(consolide=True, truncated_from=6200), ECOLE)

    assert "6200" in html
    assert "Resserrez" in html


def test_un_document_complet_n_annonce_aucune_troncature() -> None:
    html = render_fee_category_ledger_html(document(consolide=True), ECOLE)

    assert "Resserrez" not in html
