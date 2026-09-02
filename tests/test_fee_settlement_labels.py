"""Aucun état ne doit sortir d'un document sous son nom technique.

Python ne vérifie pas qu'un dictionnaire couvre toute une énumération. Un état
ajouté à `SettlementState` sans son mot français passerait donc les tests, le
lint et la revue, pour ressortir « in_kind » au milieu d'un classeur remis au
fondateur. Ce test est l'exhaustivité que le langage ne donne pas.
"""

from app.services.exports.fee_settlement_xlsx import STATE_LABEL
from app.services.fee_settlement import SettlementState


def test_chaque_etat_porte_son_mot() -> None:
    manquants = [etat.value for etat in SettlementState if etat not in STATE_LABEL]

    assert manquants == [], (
        f"États sans libellé français : {manquants}. Ajoutez-les à STATE_LABEL "
        "dans app/services/exports/fee_settlement_xlsx.py."
    )


def test_aucun_libelle_orphelin() -> None:
    """Un mot resté après le retrait d'un état ferait croire qu'il existe encore."""
    etats = set(SettlementState)

    assert set(STATE_LABEL) <= etats
