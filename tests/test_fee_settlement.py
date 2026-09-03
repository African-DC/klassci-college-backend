"""Qui a soldé quoi : ce que la case dit, et ce qu'elle ne doit pas dire.

Le tableau existe pour une question qu'aucun autre écran ne posait : sur une
classe entière, qui a soldé la scolarité et qui n'a pas remis sa tenue. Deux
confusions le videraient de son intérêt, et ces tests les gardent.

**Soldé en argent et déposé en nature ne se confondent pas.** Ce sont deux
façons de ne plus rien devoir, mais l'école ne les traite pas pareil : les
fondre en un « OK » ferait disparaître la question de la tenue.

**Ce qui reste dû l'emporte sur le reste.** Un élève qui a déposé son paquet
de rames mais doit encore la moitié de sa scolarité est en retard. Une case
qui annoncerait « déposé » le sortirait des relances.

Tests purs : ni base, ni fichier produit.
"""

from decimal import Decimal

from app.services.fee_settlement import (
    FeeLineInput,
    RowInput,
    SettlementState,
    build_matrix,
    resolve_cell,
)

SCOLARITE = 1
TENUE = 2
CANTINE = 3


class _Categorie:
    """Ce que `build_matrix` lit d'une catégorie, et rien de plus."""

    def __init__(self, name: str, priority: int) -> None:
        self.name = name
        self.priority = priority


CATEGORIES = {
    SCOLARITE: _Categorie("Scolarité", 10),
    TENUE: _Categorie("Tenue", 20),
    CANTINE: _Categorie("Cantine", 30),
}


def _frais(fee_id: int, categorie: int, statut: str, montant: str) -> FeeLineInput:
    return FeeLineInput(
        fee_id=fee_id, category_id=categorie, status=statut, amount=Decimal(montant)
    )


def _eleve(nom: str, frais: list[FeeLineInput], *, eid: int = 1, classe: str = "6e A") -> RowInput:
    return RowInput(
        enrollment_id=eid,
        student_id=eid,
        first_name="Aminata",
        last_name=nom,
        student_matricule=f"M{eid:03d}",
        # La classe situe l'eleve quand le tableau couvre toute l'ecole : deux
        # homonymes de niveaux differents seraient sinon impossibles a
        # departager sur une liste de quatre-vingt-dix-neuf lignes.
        class_name=classe,
        fees=tuple(frais),
    )


# ---------------------------------------------------------------------------
# Une case, toutes les lignes de sa catégorie réunies
# ---------------------------------------------------------------------------


def test_trois_tranches_dont_une_impayee_font_une_case_partielle() -> None:
    """Afficher l'état de la première tranche dirait « soldé » à qui doit encore."""
    lignes = [
        _frais(1, SCOLARITE, "paid", "30000"),
        _frais(2, SCOLARITE, "paid", "30000"),
        _frais(3, SCOLARITE, "pending", "30000"),
    ]
    verse = {1: Decimal("30000"), 2: Decimal("30000")}

    case = resolve_cell(SCOLARITE, lignes, verse)

    assert case.state is SettlementState.PARTIAL
    assert case.remaining == Decimal("30000")
    assert case.paid == Decimal("60000")


def test_tout_verse_donne_une_case_soldee() -> None:
    lignes = [_frais(1, SCOLARITE, "paid", "90000")]

    case = resolve_cell(SCOLARITE, lignes, {1: Decimal("90000")})

    assert case.state is SettlementState.PAID
    assert case.remaining == Decimal("0")


def test_rien_verse_donne_une_case_due_et_non_partielle() -> None:
    """On ne relance pas avec les mêmes mots qui n'a rien versé du tout."""
    case = resolve_cell(SCOLARITE, [_frais(1, SCOLARITE, "pending", "90000")], {})

    assert case.state is SettlementState.PENDING
    assert case.paid == Decimal("0")
    assert case.remaining == Decimal("90000")


def test_un_depot_en_nature_ne_se_lit_pas_comme_un_paiement() -> None:
    """La tenue remise et la scolarité payée ne se disent pas du même mot."""
    case = resolve_cell(TENUE, [_frais(1, TENUE, "in_kind", "15000")], {})

    assert case.state is SettlementState.IN_KIND
    assert case.remaining == Decimal("0")
    # Un dépôt n'est pas de l'argent : il ne gonfle ni le dû ni le versé.
    assert case.due == Decimal("0")
    assert case.paid == Decimal("0")


def test_une_exoneration_se_distingue_d_un_depot() -> None:
    """Une bourse n'est pas un paquet de rames posé sur le bureau."""
    case = resolve_cell(SCOLARITE, [_frais(1, SCOLARITE, "waived", "90000")], {})

    assert case.state is SettlementState.WAIVED
    assert case.due == Decimal("0")


def test_un_depot_ne_couvre_pas_une_ligne_encore_due_de_la_meme_categorie() -> None:
    """Ce qui reste dû l'emporte : sinon l'élève sort des relances."""
    lignes = [
        _frais(1, TENUE, "in_kind", "15000"),
        _frais(2, TENUE, "pending", "5000"),
    ]

    case = resolve_cell(TENUE, lignes, {})

    assert case.state is SettlementState.PENDING
    assert case.remaining == Decimal("5000")


def test_une_categorie_non_facturee_n_est_pas_un_impaye() -> None:
    """L'élève qui ne doit pas la cantine ne doit rien : la case est vide."""
    case = resolve_cell(CANTINE, [], {})

    assert case.state is SettlementState.ABSENT
    assert case.remaining == Decimal("0")


# ---------------------------------------------------------------------------
# Le tableau, ses colonnes et son décompte
# ---------------------------------------------------------------------------


def _matrice(eleves: list[RowInput], verse: dict[int, Decimal]):
    return build_matrix(
        eleves,
        categories=CATEGORIES,
        paid_by_fee=verse,
        class_name="6e A",
        academic_year_name="2026-2027",
    )


def test_les_colonnes_sont_les_categories_reellement_facturees() -> None:
    """Une colonne vide sur quarante élèves pousse le tableau hors de l'écran."""
    matrice = _matrice(
        [
            _eleve("Diallo", [_frais(1, SCOLARITE, "pending", "90000")]),
            _eleve("Koné", [_frais(2, TENUE, "in_kind", "15000")], eid=2),
        ],
        {},
    )

    assert [col.name for col in matrice.columns] == ["Scolarité", "Tenue"]


def test_les_colonnes_suivent_la_priorite_des_categories() -> None:
    """Le même ordre que l'état des frais d'un élève, pas l'ordre alphabétique."""
    matrice = _matrice(
        [
            _eleve(
                "Diallo",
                [
                    _frais(1, CANTINE, "pending", "5000"),
                    _frais(2, SCOLARITE, "pending", "90000"),
                ],
            )
        ],
        {},
    )

    assert [col.name for col in matrice.columns] == ["Scolarité", "Cantine"]


def test_un_eleve_qui_a_tout_depose_est_solde() -> None:
    """Le décompte compte les lignes en nature comme réglées."""
    matrice = _matrice([_eleve("Koné", [_frais(1, TENUE, "in_kind", "15000")])], {})

    assert matrice.rows[0].settled is True
    assert matrice.settled_count == 1
    assert matrice.total_count == 1


def test_un_eleve_qui_doit_encore_quelque_chose_n_est_pas_solde() -> None:
    """Déposer sa tenue ne solde pas une scolarité à moitié payée."""
    eleve = _eleve(
        "Diallo",
        [
            _frais(1, TENUE, "in_kind", "15000"),
            _frais(2, SCOLARITE, "partial", "90000"),
        ],
    )

    matrice = _matrice([eleve], {2: Decimal("45000")})

    assert matrice.rows[0].settled is False
    assert matrice.settled_count == 0


def test_chaque_ligne_porte_une_case_par_colonne() -> None:
    """Le tableau reste rectangulaire, même quand les dossiers diffèrent."""
    matrice = _matrice(
        [
            _eleve("Diallo", [_frais(1, SCOLARITE, "pending", "90000")]),
            _eleve("Koné", [_frais(2, TENUE, "in_kind", "15000")], eid=2),
        ],
        {},
    )

    assert all(len(row.cells) == len(matrice.columns) for row in matrice.rows)
    # Diallo ne doit pas la tenue : sa case est vide, pas due.
    diallo = matrice.rows[0]
    par_categorie = {cell.category_id: cell.state for cell in diallo.cells}
    assert par_categorie[TENUE] is SettlementState.ABSENT
    assert par_categorie[SCOLARITE] is SettlementState.PENDING


def test_une_classe_sans_inscription_rend_un_tableau_vide() -> None:
    """Zéro élève soldé sur zéro : aucune division, aucune colonne inventée."""
    matrice = _matrice([], {})

    assert matrice.columns == ()
    assert matrice.rows == ()
    assert matrice.settled_count == 0
    assert matrice.total_count == 0
