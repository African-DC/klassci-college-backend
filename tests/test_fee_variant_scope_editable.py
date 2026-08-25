"""La portée d'un tarif doit pouvoir être retirée, pas seulement posée.

`exclude_none=True` jetait silencieusement un `assignment_scope: null`. Un
comptable qui avait coché « non affecté » par erreur voyait le formulaire
accepter « Tous les élèves » et rien ne changeait : la seule issue était de
supprimer le tarif et de le recréer, ce que la clé étrangère refuse dès qu'un
élève est inscrit dessus.
"""

from decimal import Decimal

import pytest

from app.models.fee import FeeAssignmentScope
from app.schemas.fee import FeeVariantUpdate


def test_une_portee_envoyee_vide_est_conservee_dans_les_changements() -> None:
    data = FeeVariantUpdate.model_validate({"assignment_scope": None})
    changes = data.model_dump(exclude_unset=True, mode="json")

    assert "assignment_scope" in changes
    assert changes["assignment_scope"] is None


def test_un_champ_absent_n_est_pas_touche() -> None:
    """Modifier le seul montant ne doit pas effacer la portée au passage."""
    data = FeeVariantUpdate.model_validate({"amount": Decimal("37000")})
    changes = data.model_dump(exclude_unset=True, mode="json")

    assert "assignment_scope" not in changes
    assert "description" not in changes


def test_une_portee_mal_orthographiee_est_refusee() -> None:
    """« non-affecte » avec un tiret ne correspondrait à aucun élève.

    Le champ était une chaîne libre : la faute passait la validation et le
    tarif ne se déclenchait plus jamais, sans que rien ne le signale.
    """
    with pytest.raises(ValueError):
        FeeVariantUpdate.model_validate({"assignment_scope": "non-affecte"})


def test_les_deux_portees_du_metier_sont_acceptees() -> None:
    for valeur in (FeeAssignmentScope.AFFECTE, FeeAssignmentScope.NON_AFFECTE):
        data = FeeVariantUpdate.model_validate({"assignment_scope": valeur.value})
        assert data.assignment_scope == valeur
