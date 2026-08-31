"""Répartir un versement à la main, sans jamais trahir ce que la cascade garantit.

Le caissier ivoirien connaît un geste que la cascade seule ne sait pas dire :
« la maman pose 30 000 sur la tenue, et le reste va où il doit aller ». Le
champ `allocations` ouvre ce geste. Il ouvre aussi, s'il n'est pas tenu, la
possibilité d'imputer de l'argent sur un frais déposé en nature, sur un frais
déjà soldé, ou sur celui d'un autre élève, et d'écrire deux fois la même somme
quand une ligne est saisie deux fois.

Ces tests tiennent les deux bouts : le défaut ne bouge pas quand le champ est
absent, et chaque refus rend une phrase qu'on peut lire au guichet.

Le guichet est monté en mémoire, comme dans `test_payment_drawer_and_ventilation` :
ce qui est vérifié ici est la décision d'imputation, pas le dialecte SQL.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.dependencies import TokenData
from app.core.exceptions import BusinessValidationError
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus
from app.schemas.payment import EnrollmentPaymentCreate, PaymentAllocationItem
from app.services.payments import recording

ACTOR = TokenData(user_id=7, tenant_id="local", email="caissiere@college.ci")

INSCRIPTION = 500
PAIEMENT = 900

#: Les frais de l'inscription, dans l'ordre de priorité de la cascade.
FRAIS_INSCRIPTION = 300  # 50 000 dus
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


class _Transaction:
    """Ce que `async with db.begin_nested()` rend, sans base derrière."""

    async def __aenter__(self) -> "_Transaction":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class Caisse:
    """Le guichet en mémoire : ce qui est dû, et ce qui a fini par être écrit."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tous = [
            _frais(FRAIS_INSCRIPTION, "50000", EnrollmentFeeStatus.PENDING.value),
            _frais(FRAIS_SCOLARITE, "100000", EnrollmentFeeStatus.PENDING.value),
            _frais(FRAIS_TENUE, "30000", EnrollmentFeeStatus.PENDING.value),
            _frais(FRAIS_RAMETTE, "2500", EnrollmentFeeStatus.IN_KIND.value),
            _frais(FRAIS_COGES, "5000", EnrollmentFeeStatus.PAID.value),
        ]
        self.verse_avant: dict[int, Decimal] = {}
        self.ecrites: list[tuple[int, Decimal]] = []
        self.audit: dict[str, Any] = {}
        self._brancher(monkeypatch)

    def frais(self, fee_id: int) -> EnrollmentFee:
        return next(frais for frais in self.tous if frais.id == fee_id)

    async def verser(
        self, montant: str, *, allocations: list[tuple[int, str]] | None = None
    ) -> None:
        await recording.record_enrollment_payment(
            self.db,
            INSCRIPTION,
            EnrollmentPaymentCreate(
                amount=Decimal(montant),
                method="cash",
                allocations=[
                    PaymentAllocationItem(enrollment_fee_id=fee_id, amount=Decimal(part))
                    for fee_id, part in (allocations or [])
                ],
            ),
            actor=ACTOR,
        )

    def _brancher(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _rien(*_args: object, **_kwargs: object) -> None:
            return None

        monkeypatch.setattr(recording.payment_methods, "ensure_method_allowed", _rien)
        monkeypatch.setattr(recording.cash_session_service, "ensure_open_session", _rien)

        async def _inscription(_db: object, _id: int) -> object:
            return MagicMock(id=INSCRIPTION)

        async def _tous(_db: object, _id: int) -> list[EnrollmentFee]:
            return self.tous

        async def _deja_verse(_db: object, _id: int) -> dict[int, Decimal]:
            return dict(self.verse_avant)

        async def _create_payment(_db: object, **_kwargs: object) -> object:
            return MagicMock(id=PAIEMENT)

        async def _create_allocation(
            _db: object, *, payment_id: int, enrollment_fee_id: int, amount: Decimal
        ) -> object:
            self.ecrites.append((enrollment_fee_id, amount))
            return MagicMock(id=payment_id)

        async def _apres(_db: object, fees: list[EnrollmentFee]) -> dict[int, Decimal]:
            return {
                frais.id: self.verse_avant.get(frais.id, Decimal("0"))
                + sum((part for fee_id, part in self.ecrites if fee_id == frais.id), Decimal("0"))
                for frais in fees
            }

        async def _audit(_db: object, **kwargs: Any) -> None:
            self.audit = kwargs.get("new_values") or {}

        async def _relu(_db: object, _id: int) -> object:
            return MagicMock(id=PAIEMENT, enrollment=None)

        monkeypatch.setattr(recording.repo, "get_enrollment_for_update", _inscription)
        monkeypatch.setattr(recording.repo, "get_enrollment_fees_ordered_by_priority", _tous)
        monkeypatch.setattr(recording.repo, "create_payment", _create_payment)
        monkeypatch.setattr(recording.repo, "create_allocation", _create_allocation)
        monkeypatch.setattr(recording.repo, "get_payment_with_allocations", _relu)
        monkeypatch.setattr(recording.fees_paid, "paid_by_enrollment", _deja_verse)
        monkeypatch.setattr(recording, "paid_for_fees", _apres)
        monkeypatch.setattr(recording, "audit_log", _audit)
        monkeypatch.setattr(recording, "dispatch_payment_notification", AsyncMock())
        monkeypatch.setattr(recording, "payment_to_response", lambda payment: payment)

        self.db = MagicMock()
        self.db.begin_nested = MagicMock(return_value=_Transaction())
        self.db.flush = AsyncMock()
        self.db.commit = AsyncMock()


@pytest.fixture
def caisse(monkeypatch: pytest.MonkeyPatch) -> Caisse:
    return Caisse(monkeypatch)


def _total(caisse: Caisse) -> Decimal:
    return sum((part for _fee_id, part in caisse.ecrites), Decimal("0"))


# ---------------------------------------------------------------------------
# Le défaut ne bouge pas
# ---------------------------------------------------------------------------


async def test_sans_repartition_la_cascade_reste_le_defaut(caisse: Caisse) -> None:
    """Un client qui n'envoie rien de neuf obtient exactement ce qu'il obtenait."""
    await caisse.verser("60000")

    assert caisse.ecrites == [
        (FRAIS_INSCRIPTION, Decimal("50000")),
        (FRAIS_SCOLARITE, Decimal("10000")),
    ]
    assert caisse.audit["allocation_mode"] == "cascade"
    assert "directed_allocations" not in caisse.audit


# ---------------------------------------------------------------------------
# La répartition demandée est tenue
# ---------------------------------------------------------------------------


async def test_une_imputation_nommee_va_exactement_au_frais_designe(caisse: Caisse) -> None:
    """30 000 sur la tenue : l'inscription, pourtant prioritaire, ne reçoit rien."""
    await caisse.verser("30000", allocations=[(FRAIS_TENUE, "30000")])

    assert caisse.ecrites == [(FRAIS_TENUE, Decimal("30000"))]
    assert caisse.frais(FRAIS_TENUE).status == EnrollmentFeeStatus.PAID.value
    assert caisse.frais(FRAIS_INSCRIPTION).status == EnrollmentFeeStatus.PENDING.value


async def test_le_reliquat_cascade_sur_les_frais_restants(caisse: Caisse) -> None:
    """« 30 000 sur la tenue, le reste où il doit aller » : le reste suit la priorité."""
    await caisse.verser("80000", allocations=[(FRAIS_TENUE, "30000")])

    assert caisse.ecrites == [
        (FRAIS_INSCRIPTION, Decimal("50000")),
        (FRAIS_TENUE, Decimal("30000")),
    ]
    assert _total(caisse) == Decimal("80000"), "la somme des imputations vaut le versement"


async def test_un_frais_nomme_deux_fois_ne_recoit_quune_seule_ligne(caisse: Caisse) -> None:
    """Deux lignes sur un même frais font une imputation, pas deux écritures."""
    await caisse.verser(
        "50000",
        allocations=[(FRAIS_INSCRIPTION, "20000"), (FRAIS_INSCRIPTION, "30000")],
    )

    assert caisse.ecrites == [(FRAIS_INSCRIPTION, Decimal("50000"))]
    assert caisse.frais(FRAIS_INSCRIPTION).status == EnrollmentFeeStatus.PAID.value
    assert caisse.audit["directed_allocations"] == [
        {"enrollment_fee_id": FRAIS_INSCRIPTION, "amount": "50000"}
    ]


async def test_une_imputation_partielle_laisse_le_frais_en_partiel(caisse: Caisse) -> None:
    await caisse.verser("20000", allocations=[(FRAIS_SCOLARITE, "20000")])

    assert caisse.ecrites == [(FRAIS_SCOLARITE, Decimal("20000"))]
    assert caisse.frais(FRAIS_SCOLARITE).status == EnrollmentFeeStatus.PARTIAL.value


# ---------------------------------------------------------------------------
# Ce que la répartition ne peut pas se permettre
# ---------------------------------------------------------------------------


async def test_une_repartition_superieure_au_versement_est_refusee(caisse: Caisse) -> None:
    with pytest.raises(BusinessValidationError) as refus:
        await caisse.verser(
            "60000",
            allocations=[(FRAIS_INSCRIPTION, "50000"), (FRAIS_TENUE, "30000")],
        )

    assert refus.value.status_code == 422
    assert "dépasse le montant versé" in refus.value.detail
    assert caisse.ecrites == [], "rien n'est écrit quand la répartition est refusée"


async def test_une_imputation_superieure_au_reste_du_est_refusee(caisse: Caisse) -> None:
    """Y compris quand ce sont deux lignes cumulées qui font le dépassement."""
    with pytest.raises(BusinessValidationError) as refus:
        await caisse.verser(
            "70000",
            allocations=[(FRAIS_INSCRIPTION, "40000"), (FRAIS_INSCRIPTION, "30000")],
        )

    assert refus.value.status_code == 422
    assert "ne peut recevoir que 50000 XOF" in refus.value.detail
    assert caisse.ecrites == []


async def test_un_frais_dune_autre_inscription_est_refuse(caisse: Caisse) -> None:
    with pytest.raises(BusinessValidationError) as refus:
        await caisse.verser("10000", allocations=[(FRAIS_AUTRE_ELEVE, "10000")])

    assert refus.value.status_code == 422
    assert "n'appartient pas à cette inscription" in refus.value.detail
    assert caisse.ecrites == []


async def test_un_frais_regle_en_nature_est_refuse(caisse: Caisse) -> None:
    """Une ramette déposée n'attend plus d'argent : aucun versement ne s'y impute."""
    with pytest.raises(BusinessValidationError) as refus:
        await caisse.verser("2500", allocations=[(FRAIS_RAMETTE, "2500")])

    assert refus.value.status_code == 422
    assert "réglé en nature" in refus.value.detail
    assert caisse.frais(FRAIS_RAMETTE).status == EnrollmentFeeStatus.IN_KIND.value
    assert caisse.ecrites == []


async def test_un_frais_deja_solde_est_refuse(caisse: Caisse) -> None:
    with pytest.raises(BusinessValidationError) as refus:
        await caisse.verser("5000", allocations=[(FRAIS_COGES, "5000")])

    assert refus.value.status_code == 422
    assert "déjà soldé" in refus.value.detail
    assert caisse.ecrites == []


async def test_un_montant_dimputation_negatif_est_refuse_a_la_porte(caisse: Caisse) -> None:
    """Le schéma refuse avant même d'atteindre la caisse."""
    with pytest.raises(ValueError, match="positive"):
        EnrollmentPaymentCreate(
            amount=Decimal("10000"),
            method="cash",
            allocations=[PaymentAllocationItem(enrollment_fee_id=FRAIS_TENUE, amount=Decimal("0"))],
        )


# ---------------------------------------------------------------------------
# Le journal
# ---------------------------------------------------------------------------


async def test_le_journal_distingue_ce_qui_est_choisi_de_ce_qui_est_calcule(
    caisse: Caisse,
) -> None:
    """L'audit doit rester lisible par un contrôleur qui n'était pas au guichet."""
    await caisse.verser("80000", allocations=[(FRAIS_TENUE, "30000")])

    assert caisse.audit["allocation_mode"] == "manual"
    assert caisse.audit["directed_allocations"] == [
        {"enrollment_fee_id": FRAIS_TENUE, "amount": "30000"}
    ]
    assert caisse.audit["allocations"] == [
        {"enrollment_fee_id": FRAIS_INSCRIPTION, "amount": "50000"},
        {"enrollment_fee_id": FRAIS_TENUE, "amount": "30000"},
    ]
    assert caisse.audit["amount"] == "80000"


async def test_le_champ_absent_et_le_champ_nul_disent_la_meme_chose() -> None:
    """Un formulaire qui n'a rien coché envoie tantôt rien, tantôt `null`."""
    absent = EnrollmentPaymentCreate(amount=Decimal("1000"), method="cash")
    nul = EnrollmentPaymentCreate.model_validate(
        {"amount": Decimal("1000"), "method": "cash", "allocations": None}
    )

    assert absent.allocations == []
    assert nul.allocations == []
