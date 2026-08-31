"""L'aperçu répond exactement ce que la caisse fera, y compris quand elle refusera.

L'écran d'encaissement ne calcule plus la répartition de son côté : il affiche
celle que rend cet aperçu. C'est ce qui permet à la règle de priorité, au reste
dû et au traitement des frais en nature de n'exister qu'à un seul endroit.

D'où deux propriétés qui comptent autant l'une que l'autre. L'aperçu et
l'enregistrement passent par la même vérification, donc l'écran ne peut pas
promettre une imputation que la caisse refuserait. Et ce qui empêche
d'enregistrer est **rendu**, jamais levé : le caissier tape, l'aperçu explique,
rien n'est écrit. Une exception blanchirait l'écran à chaque frappe
intermédiaire.
"""

from decimal import Decimal

import pytest

from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.services.payments import preview

INSCRIPTION = 500

FRAIS_INSCRIPTION = 300  # 50 000 dus, priorité la plus haute
FRAIS_SCOLARITE = 301  # 100 000 dus
FRAIS_TENUE = 302  # 30 000 dus
FRAIS_RAMETTE = 303  # déposée en nature : plus rien en argent
FRAIS_COGES = 304  # déjà soldé
FRAIS_AUTRE_ELEVE = 999  # n'appartient pas à cette inscription


def _frais(fee_id: int, montant: str, statut: str) -> EnrollmentFee:
    return EnrollmentFee(
        id=fee_id,
        enrollment_id=INSCRIPTION,
        fee_variant_id=fee_id,
        fee_category_id=fee_id,
        amount=Decimal(montant),
        status=statut,
    )


TOUS = [
    _frais(FRAIS_INSCRIPTION, "50000", EnrollmentFeeStatus.PENDING.value),
    _frais(FRAIS_SCOLARITE, "100000", EnrollmentFeeStatus.PENDING.value),
    _frais(FRAIS_TENUE, "30000", EnrollmentFeeStatus.PENDING.value),
    _frais(FRAIS_RAMETTE, "2500", EnrollmentFeeStatus.IN_KIND.value),
    _frais(FRAIS_COGES, "5000", EnrollmentFeeStatus.PAID.value),
]


@pytest.fixture
def guichet(monkeypatch: pytest.MonkeyPatch) -> object:
    """L'inscription en mémoire : ses frais, et ce qui y est déjà versé."""

    async def _tous(_db: object, _id: int) -> list[EnrollmentFee]:
        return TOUS

    async def _deja_verse(_db: object, _id: int) -> dict[int, Decimal]:
        return {FRAIS_COGES: Decimal("5000")}

    monkeypatch.setattr(preview.repo, "get_enrollment_fees_ordered_by_priority", _tous)
    monkeypatch.setattr(preview.fees_paid, "paid_by_enrollment", _deja_verse)
    return object()


async def _apercu(montant: str, directed: dict[int, str] | None = None):
    return await preview.preview_allocation(
        None,  # type: ignore[arg-type]
        INSCRIPTION,
        Decimal(montant),
        directed={fee_id: Decimal(v) for fee_id, v in (directed or {}).items()},
    )


def _ligne(apercu, fee_id: int):
    return next(ligne for ligne in apercu.lines if ligne.enrollment_fee_id == fee_id)


# ---------------------------------------------------------------------------
# Sans répartition nommée, l'aperçu ne bouge pas
# ---------------------------------------------------------------------------


async def test_sans_repartition_l_apercu_montre_la_cascade(guichet: object) -> None:
    """60 000 remplissent l'inscription puis débordent sur la scolarité."""
    apercu = await _apercu("60000")

    assert _ligne(apercu, FRAIS_INSCRIPTION).allocated == Decimal("50000")
    assert _ligne(apercu, FRAIS_SCOLARITE).allocated == Decimal("10000")
    assert _ligne(apercu, FRAIS_TENUE).allocated == Decimal("0")
    assert apercu.can_record is True
    assert apercu.problems == []
    assert apercu.directed_total == Decimal("0")
    assert apercu.cascaded_total == Decimal("60000")


async def test_le_reste_du_est_rendu_au_lieu_d_etre_calcule_par_l_ecran(guichet: object) -> None:
    """`cash_remaining_before` porte la règle, l'écran ne la rejoue pas.

    Un frais déposé en nature et un frais soldé n'attendent plus d'argent : ils
    valent zéro, sans que le client ait à connaître la notion.
    """
    apercu = await _apercu("1000")

    assert _ligne(apercu, FRAIS_INSCRIPTION).cash_remaining_before == Decimal("50000")
    assert _ligne(apercu, FRAIS_RAMETTE).cash_remaining_before == Decimal("0")
    assert _ligne(apercu, FRAIS_COGES).cash_remaining_before == Decimal("0")


# ---------------------------------------------------------------------------
# La répartition nommée est celle qui s'affiche
# ---------------------------------------------------------------------------


async def test_une_imputation_nommee_apparait_telle_quelle(guichet: object) -> None:
    """30 000 sur la tenue : l'inscription, pourtant prioritaire, ne reçoit rien."""
    apercu = await _apercu("30000", {FRAIS_TENUE: "30000"})

    tenue = _ligne(apercu, FRAIS_TENUE)
    assert tenue.directed == Decimal("30000")
    assert tenue.allocated == Decimal("30000")
    assert _ligne(apercu, FRAIS_INSCRIPTION).allocated == Decimal("0")
    assert apercu.directed_total == Decimal("30000")
    assert apercu.cascaded_total == Decimal("0")
    assert apercu.can_record is True


async def test_le_reliquat_non_nomme_cascade_par_dessus(guichet: object) -> None:
    """« 30 000 sur la tenue, le reste où il doit aller » : le geste du guichet."""
    apercu = await _apercu("80000", {FRAIS_TENUE: "30000"})

    assert _ligne(apercu, FRAIS_TENUE).allocated == Decimal("30000")
    assert _ligne(apercu, FRAIS_INSCRIPTION).allocated == Decimal("50000")
    assert apercu.directed_total == Decimal("30000")
    assert apercu.cascaded_total == Decimal("50000")


async def test_la_cascade_ne_re_remplit_pas_un_frais_deja_servi(guichet: object) -> None:
    """Le reliquat se pose sur ce qui reste dû APRÈS les imputations nommées."""
    apercu = await _apercu("50000", {FRAIS_INSCRIPTION: "20000"})

    inscription = _ligne(apercu, FRAIS_INSCRIPTION)
    assert inscription.directed == Decimal("20000")
    # 20 000 nommés + 30 000 cascadés, soit exactement les 50 000 dus.
    assert inscription.allocated == Decimal("50000")
    assert apercu.surplus == Decimal("0")


# ---------------------------------------------------------------------------
# Ce qui bloque est rendu, jamais levé
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fee_id", "extrait"),
    [
        (FRAIS_RAMETTE, "réglé en nature"),
        (FRAIS_COGES, "déjà soldé"),
        (FRAIS_AUTRE_ELEVE, "n'appartient pas à cette inscription"),
    ],
)
async def test_un_frais_qui_n_attend_plus_d_argent_est_explique(
    guichet: object, fee_id: int, extrait: str
) -> None:
    """L'aperçu répond 200 avec le motif, il ne lève pas."""
    apercu = await _apercu("1000", {fee_id: "1000"})

    assert apercu.can_record is False
    assert [p.enrollment_fee_id for p in apercu.problems] == [fee_id]
    assert extrait in apercu.problems[0].message
    assert apercu.reject_reason == apercu.problems[0].message


async def test_imputer_plus_que_le_reste_du_est_explique(guichet: object) -> None:
    apercu = await _apercu("60000", {FRAIS_TENUE: "60000"})

    assert apercu.can_record is False
    assert "ne peut recevoir que 30000" in apercu.problems[0].message


async def test_repartir_plus_que_le_montant_verse_est_explique(guichet: object) -> None:
    """Le problème porte sur la répartition entière, pas sur une ligne."""
    apercu = await _apercu("40000", {FRAIS_INSCRIPTION: "30000", FRAIS_TENUE: "30000"})

    assert apercu.can_record is False
    assert apercu.problems[0].enrollment_fee_id is None
    assert "dépasse le montant versé" in apercu.problems[0].message


async def test_une_repartition_refusee_n_affiche_aucune_allocation(guichet: object) -> None:
    """Montrer une répartition que la caisse refuserait ferait croire qu'il suffit de valider."""
    apercu = await _apercu("60000", {FRAIS_TENUE: "60000"})

    assert all(ligne.allocated == Decimal("0") for ligne in apercu.lines)
    assert apercu.directed_total == Decimal("0")
    assert apercu.cascaded_total == Decimal("0")


async def test_le_surplus_reste_un_refus(guichet: object) -> None:
    """La dette servable vaut 180 000 : au-delà, rien n'est enregistrable."""
    apercu = await _apercu("200000")

    assert apercu.can_record is False
    assert apercu.surplus == Decimal("20000")
    assert apercu.reject_reason is not None
    assert "supérieur à la dette restante" in apercu.reject_reason
