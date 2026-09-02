"""Un export doit dire sur quoi l'argent est parti, pas en nommer un tiers.

La colonne « Frais » du journal montrait le premier frais et comptait les
autres : `Scolarité (+2)`. Le comptable qui tire l'export sans filtre ne
pouvait donc pas savoir sur quoi les 85 000 F d'une famille étaient partis,
et les deux catégories cachées ne figuraient nulle part ailleurs dans le
document — ni en pied de page, ni dans le récapitulatif, qui groupe par moyen
de paiement et par caisse, jamais par frais.

Ces tests gardent trois choses. Que toutes les catégories sortent. Que les
parts d'une même catégorie se cumulent au lieu de se répéter. Et que la somme
des parts affichées égale le montant de la ligne — sans quoi un export dont on
refait la somme dans le tableur ne retomberait pas sur ses pieds, ce qui est
exactement ce qu'on demande à un journal de caisse.

Tests purs : ni base, ni fichier produit.
"""

from decimal import Decimal

from app.services.payments.journal_data import UNALLOCATED, FeeShare
from app.services.payments.journal_labels import fee_cell
from app.services.payments_journal_service import _fee_shares


class _Categorie:
    def __init__(self, name: str) -> None:
        self.name = name


class _Variante:
    def __init__(self, categorie: _Categorie | None) -> None:
        self.category = categorie


class _Frais:
    def __init__(self, categorie: _Categorie | None) -> None:
        self.fee_variant = _Variante(categorie)


class _Imputation:
    def __init__(self, categorie: str | None, montant: str) -> None:
        self.enrollment_fee = _Frais(_Categorie(categorie) if categorie else None)
        self.amount = Decimal(montant)


class _Versement:
    """Ce que `_fee_shares` lit d'un versement, et rien de plus."""

    def __init__(self, montant: str, imputations: list[_Imputation]) -> None:
        self.amount = Decimal(montant)
        self.allocations = imputations


def test_les_trois_categories_sortent_toutes() -> None:
    """Aucune n'est cachée derrière un compteur."""
    versement = _Versement(
        "50000",
        [
            _Imputation("Scolarité", "30000"),
            _Imputation("Cantine", "12000"),
            _Imputation("Transport", "8000"),
        ],
    )

    assert _fee_shares(versement) == (
        FeeShare("Scolarité", Decimal("30000")),
        FeeShare("Cantine", Decimal("12000")),
        FeeShare("Transport", Decimal("8000")),
    )


def test_deux_tranches_d_une_meme_categorie_se_cumulent() -> None:
    """« Scolarité 60 000 », pas deux lignes à additionner de tête."""
    versement = _Versement(
        "60000",
        [_Imputation("Scolarité", "20000"), _Imputation("Scolarité", "40000")],
    )

    assert _fee_shares(versement) == (FeeShare("Scolarité", Decimal("60000")),)


def test_la_somme_des_parts_egale_le_montant_de_la_ligne() -> None:
    """Ce que le versement porte au-delà de ses imputations est nommé.

    L'invariant comptable veut ce reste nul. Quand il ne l'est pas, le taire
    donnerait un export dont la colonne « Frais » ne se raccorde pas à la
    colonne « Montant », sans que rien ne le signale.
    """
    versement = _Versement("50000", [_Imputation("Scolarité", "30000")])

    parts = _fee_shares(versement)
    assert parts == (
        FeeShare("Scolarité", Decimal("30000")),
        FeeShare(UNALLOCATED, Decimal("20000")),
    )
    assert sum(part.amount for part in parts) == versement.amount


def test_un_versement_sans_imputation_dit_ce_qu_il_porte() -> None:
    """« — » sur de l'argent réellement encaissé ne renseignait personne."""
    assert _fee_shares(_Versement("15000", [])) == (FeeShare(UNALLOCATED, Decimal("15000")),)


def test_une_categorie_sans_nom_ne_fabrique_pas_de_ligne_vide() -> None:
    """Le montant reste visible, sous le seul nom qu'on puisse en donner."""
    assert _fee_shares(_Versement("9000", [_Imputation(None, "9000")])) == (
        FeeShare(UNALLOCATED, Decimal("9000")),
    )


def test_la_cellule_empile_une_categorie_par_ligne() -> None:
    """Le PDF et le classeur lisent cette fonction, donc la même chose.

    L'espace des milliers est insécable, comme partout ailleurs dans les
    documents : c'est ce qui empêche « 30 » de finir seul en bout de ligne.
    Le test l'écrit explicitement pour qu'un passage à l'espace ordinaire se
    remarque ici plutôt que dans un PDF déjà signé.
    """
    nbsp = "\u00a0"
    cellule = fee_cell(
        (
            FeeShare("Scolarité", Decimal("30000")),
            FeeShare("Cantine", Decimal("12000")),
        )
    )

    assert cellule == f"Scolarité 30{nbsp}000\nCantine 12{nbsp}000"


def test_la_cellule_vide_reste_un_tiret() -> None:
    """Rien à dire se dit comme avant : la colonne ne change pas de langage."""
    assert fee_cell(()) == "—"
