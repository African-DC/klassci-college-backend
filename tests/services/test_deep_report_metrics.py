"""Seuils de moyenne et agrégats du rapport DEEP.

Ce sont les chiffres que l'inspection relit ligne à ligne. Une borne posée du
mauvais côté ne se voit pas à l'œil nu sur un tableau imprimé et fausse tout
un récapitulatif : les cas limites 10,00 et 08,50 sont donc testés
explicitement.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.deep_report._metrics import (
    BandTally,
    Cycle,
    GradeBand,
    SexCount,
    band_of,
    cycle_of_level,
    format_average,
    percentage,
    sum_tallies,
)
from app.services.deep_report._types import MISSING


def _d(value: str) -> Decimal:
    return Decimal(value)


# ---------------------------------------------------------------------------
# Seuils de tranche
# ---------------------------------------------------------------------------


def test_dix_pile_est_une_reussite():
    """« Moy ≥ 10 » : la borne appartient à la tranche du dessus."""
    assert band_of(_d("10.00")) is GradeBand.PASS


def test_juste_sous_dix_bascule_en_tranche_intermediaire():
    assert band_of(_d("9.99")) is GradeBand.BORDERLINE


def test_huit_cinquante_pile_est_intermediaire():
    """« 08.50 ≤ Moy < 10.00 » : 8,50 n'est pas un échec."""
    assert band_of(_d("8.50")) is GradeBand.BORDERLINE


def test_juste_sous_huit_cinquante_est_un_echec():
    assert band_of(_d("8.49")) is GradeBand.FAIL


def test_zero_est_un_echec():
    assert band_of(_d("0.00")) is GradeBand.FAIL


def test_vingt_est_une_reussite():
    assert band_of(_d("20.00")) is GradeBand.PASS


def test_sans_moyenne_aucune_tranche():
    """Un élève non classé n'a pas échoué : il n'a pas été évalué."""
    assert band_of(None) is None


# ---------------------------------------------------------------------------
# Pourcentages
# ---------------------------------------------------------------------------


def test_pourcentage_sur_denominateur_nul_reste_vide():
    """Zéro pour cent affirmerait un taux constaté sur un effectif inexistant."""
    assert percentage(0, 0) == MISSING


def test_pourcentage_formate_a_la_francaise():
    assert percentage(1, 3) == "33,3 %"


def test_pourcentage_complet():
    assert percentage(7, 7) == "100,0 %"


def test_moyenne_formatee_avec_virgule():
    assert format_average(_d("12.5")) == "12,50"
    assert format_average(None) == MISSING


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------


def test_premier_cycle_de_la_sixieme_a_la_troisieme():
    for name in ("6ème", "5e", "4ème A", "3e"):
        assert cycle_of_level(name, 1) is Cycle.FIRST


def test_second_cycle_du_lycee():
    for name in ("2nde", "Seconde C", "1ère D", "Terminale A", "Tle C"):
        assert cycle_of_level(name, 5) is Cycle.SECOND


def test_niveau_inconnu_retombe_sur_le_rang():
    """Un intitulé exotique ne doit pas envoyer tout le lycée en 1er cycle."""
    assert cycle_of_level("Classe préparatoire", 2) is Cycle.FIRST
    assert cycle_of_level("Classe préparatoire", 6) is Cycle.SECOND


# ---------------------------------------------------------------------------
# Décomptes et totaux
# ---------------------------------------------------------------------------


def test_sexe_non_renseigne_compte_dans_le_total_mais_pas_en_f_ni_g():
    count = SexCount().plus(girl=True).plus(girl=False).plus(girl=None)
    assert (count.girls, count.boys, count.unknown) == (1, 1, 1)
    assert count.total == 3


def test_tally_ventile_les_trois_tranches():
    tally = BandTally()
    tally = tally.with_student(girl=True, average=_d("14.00"))
    tally = tally.with_student(girl=False, average=_d("9.00"))
    tally = tally.with_student(girl=True, average=_d("8.00"))
    tally = tally.with_student(girl=False, average=None)

    assert tally.real.total == 4
    assert tally.ranked.total == 3
    assert tally.passed.total == 1
    assert tally.borderline.total == 1
    assert tally.failed.total == 1


def test_eleve_sans_bulletin_ne_gonfle_pas_l_echec():
    tally = BandTally().with_student(girl=True, average=None)
    assert tally.real.total == 1
    assert tally.ranked.total == 0
    assert tally.failed.total == 0


def test_somme_de_recapitulatifs_additionne_chaque_tranche():
    first = BandTally().with_student(girl=True, average=_d("12.00"))
    second = BandTally().with_student(girl=False, average=_d("7.00"))
    third = BandTally().with_student(girl=None, average=_d("9.50"))

    total = sum_tallies([first, second, third])
    assert total.real.total == 3
    assert total.real.girls == 1
    assert total.real.boys == 1
    assert total.real.unknown == 1
    assert total.passed.total == 1
    assert total.borderline.total == 1
    assert total.failed.total == 1


def test_somme_vide_est_neutre():
    assert sum_tallies([]).real.total == 0
