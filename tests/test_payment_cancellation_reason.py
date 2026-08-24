"""Le motif d'une annulation de versement, et ce qu'il vaut.

Une annulation d'encaissement est exactement l'écriture qu'un contrôle vient
relire. Sans phrase qui la justifie, elle ne se défend pas — et un caissier qui
pourrait annuler sans rien écrire pourrait encaisser puis effacer.

Ces tests portent sur la seule garde du motif. La réversibilité elle-même —
le solde qui revient exactement à zéro, les allocations qui survivent — est
couverte par `tests/services/test_payment_cancel_reversal.py`, écrit en même
temps : elle ne l'était pas, malgré ce que cette phrase affirmait avant.
"""

import pytest

from app.core.exceptions import BusinessValidationError
from app.services.payments.lifecycle import MOTIF_MAXIMUM, _motif_valide


def test_un_motif_ecrit_est_conserve_tel_quel() -> None:
    assert (
        _motif_valide("Montant saisi en double, la caisse ne contient que 5 000 F.")
        == "Montant saisi en double, la caisse ne contient que 5 000 F."
    )


@pytest.mark.parametrize("motif", ["", "   ", "erreur", "test", "ok", "à annuler"])
def test_un_mot_ne_vaut_pas_un_motif(motif: str) -> None:
    """« erreur » ne dit rien à qui relira le bordereau dans six mois."""
    with pytest.raises(BusinessValidationError) as leve:
        _motif_valide(motif)
    assert "motif" in leve.value.detail.lower()


def test_le_motif_est_normalise_avant_d_etre_mesure() -> None:
    """Des espaces ne font pas une phrase, et n'allongent pas artificiellement."""
    with pytest.raises(BusinessValidationError):
        _motif_valide("erreur   \n\t  de   saisie"[:9])

    assert _motif_valide("  Erreur   de\n\tsaisie  au  guichet ") == "Erreur de saisie au guichet"


def test_un_motif_tres_long_est_borne_a_la_colonne() -> None:
    """La colonne fait 500 caractères : au-delà, MySQL tronquerait sans le dire.

    Le schéma laisse passer jusqu'à 2 000 caractères — il ne borne que la
    taille du corps reçu, pas la règle métier — donc cette troncature est
    atteignable par l'API.
    """
    resultat = _motif_valide("Annulation " + "x" * 900)
    assert len(resultat) == MOTIF_MAXIMUM
