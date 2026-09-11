"""Déplacer une imputation vers le bon frais, sans annuler le versement.

Le cas fondateur, collège Rostan, 11/09/2026 : 3 000 F posés sur un article
que la famille avait apporté en nature, sur un versement de 164 000 F. La
seule issue était d'annuler les 164 000 et de les ressaisir — le journal de
caisse aurait gardé une annulation hors de proportion avec l'erreur.

Les tests tournent sur SQLite, comme `test_in_kind_deposits`.
"""

from collections.abc import Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import Integer, MetaData, Table, create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import BusinessValidationError, ConflictError
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    EnrollmentFee,
    EnrollmentFeeStatus,
    FeeCategory,
    FeeVariant,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
)
from app.services.payments import reallocation

AY = 2026
INSCRIPTION = 500
CAISSIER = 10

CAT_RAM = 100
CAT_SCOLARITE = 101
CAT_TENUE = 102
CAT_LIVRET = 103
VAR_RAM = 200
VAR_SCOLARITE = 201
VAR_TENUE = 202
VAR_LIVRET = 203
FRAIS_RAM = 300
FRAIS_SCOLARITE = 301
FRAIS_TENUE = 302
FRAIS_LIVRET = 303

VERSEMENT = 900

_TABLES = (
    "enrollments",
    "enrollment_fees",
    "fee_categories",
    "fee_variants",
    "payments",
    "payment_allocations",
)


class _AsyncBridge:
    """Une session synchrone déguisée en `AsyncSession`.

    `begin_nested` et `commit` sont ici parce que le service en pose : il écrit
    de l'argent, et il le fait dans une transaction. Les rendre inertes plutôt
    que de les retirer du service garde le test sur le vrai chemin.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def delete(self, instance: object) -> None:
        self._session.delete(instance)

    async def commit(self) -> None:
        self._session.flush()

    def begin_nested(self) -> "_NoopTransaction":
        return _NoopTransaction()


class _NoopTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _sqlite_schema() -> list[Table]:
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)

    tables = []
    for nom in _TABLES:
        table = miroir.tables[nom]
        table.c.id.type = Integer()
        tables.append(table)
    return tables


@pytest.fixture
def db() -> Iterator[_AsyncBridge]:
    engine = create_engine("sqlite://")
    for table in _sqlite_schema():
        table.create(engine)

    with Session(engine) as session:
        session.add_all(
            [
                Enrollment(
                    id=INSCRIPTION,
                    student_id=1,
                    class_id=1,
                    academic_year_id=AY,
                    status=EnrollmentStatus.VALIDE,
                ),
                FeeCategory(
                    id=CAT_RAM, name="PAQUET DE RAM", is_mandatory=True, accepts_in_kind=True
                ),
                FeeCategory(id=CAT_SCOLARITE, name="Scolarite", is_mandatory=True),
                FeeCategory(id=CAT_TENUE, name="Tenue", is_mandatory=True),
                FeeCategory(id=CAT_LIVRET, name="Livret scolaire", is_mandatory=True),
                FeeVariant(
                    id=VAR_RAM, fee_category_id=CAT_RAM, academic_year_id=AY, amount=Decimal("3000")
                ),
                FeeVariant(
                    id=VAR_SCOLARITE,
                    fee_category_id=CAT_SCOLARITE,
                    academic_year_id=AY,
                    amount=Decimal("120000"),
                ),
                FeeVariant(
                    id=VAR_TENUE,
                    fee_category_id=CAT_TENUE,
                    academic_year_id=AY,
                    amount=Decimal("18000"),
                ),
                FeeVariant(
                    id=VAR_LIVRET,
                    fee_category_id=CAT_LIVRET,
                    academic_year_id=AY,
                    amount=Decimal("2000"),
                ),
                EnrollmentFee(
                    id=FRAIS_RAM,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_RAM,
                    fee_category_id=CAT_RAM,
                    amount=Decimal("3000"),
                    status=EnrollmentFeeStatus.PAID,
                ),
                EnrollmentFee(
                    id=FRAIS_SCOLARITE,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_SCOLARITE,
                    fee_category_id=CAT_SCOLARITE,
                    amount=Decimal("120000"),
                    status=EnrollmentFeeStatus.PARTIAL,
                ),
                EnrollmentFee(
                    id=FRAIS_TENUE,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_TENUE,
                    fee_category_id=CAT_TENUE,
                    amount=Decimal("18000"),
                    status=EnrollmentFeeStatus.PAID,
                ),
                # Ce frais-la ne porte aucune imputation : c'est le sujet du test
                # qui verifie qu'on ne deplace pas ce qui n'a jamais ete pose.
                EnrollmentFee(
                    id=FRAIS_LIVRET,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VAR_LIVRET,
                    fee_category_id=CAT_LIVRET,
                    amount=Decimal("2000"),
                    status=EnrollmentFeeStatus.PENDING,
                ),
            ]
        )
        session.flush()

        # Le versement du cas reel, en reduit : 104 000 F ventiles sur trois
        # frais, dont 3 000 sur l'article apporte en nature.
        session.add(
            Payment(
                id=VERSEMENT,
                enrollment_id=INSCRIPTION,
                amount=Decimal("104000"),
                method=PaymentMethod.CASH,
                status=PaymentStatus.COMPLETED,
                received_by=CAISSIER,
            )
        )
        session.flush()
        session.add_all(
            [
                PaymentAllocation(
                    payment_id=VERSEMENT, enrollment_fee_id=FRAIS_RAM, amount=Decimal("3000")
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT,
                    enrollment_fee_id=FRAIS_SCOLARITE,
                    amount=Decimal("83000"),
                ),
                PaymentAllocation(
                    payment_id=VERSEMENT, enrollment_fee_id=FRAIS_TENUE, amount=Decimal("18000")
                ),
            ]
        )
        session.flush()
        yield _AsyncBridge(session)

    engine.dispose()


def _imputations(db: _AsyncBridge) -> dict[int, Decimal]:
    lignes = (
        db._session.query(PaymentAllocation).filter(PaymentAllocation.payment_id == VERSEMENT).all()
    )
    return {int(a.enrollment_fee_id): Decimal(str(a.amount)) for a in lignes}


async def _deplacer(
    db: _AsyncBridge,
    *,
    depuis: int = FRAIS_RAM,
    vers: int = FRAIS_SCOLARITE,
    montant: str = "3000",
    motif: str = "Article apporte en nature, imputation posee sur le mauvais frais.",
    par: int = CAISSIER,
    tout_pouvoir: bool = True,
) -> object:
    with (
        patch("app.services.payments.reallocation.audit_log", new=AsyncMock()),
        patch(
            "app.services.payments.reallocation.payment_to_response",
            new=lambda payment: payment,
        ),
        patch(
            "app.services.payments.reallocation.repo.get_payment_with_allocations",
            new=AsyncMock(return_value=db._session.get(Payment, VERSEMENT)),
        ),
    ):
        return await reallocation.reallocate_payment(
            db,  # type: ignore[arg-type]
            VERSEMENT,
            from_fee_id=depuis,
            to_fee_id=vers,
            amount=Decimal(montant),
            reason=motif,
            reallocated_by=par,
            may_reallocate_any=tout_pouvoir,
        )


# ---------------------------------------------------------------------------
# Le geste lui-meme
# ---------------------------------------------------------------------------


async def test_le_montant_change_de_frais_et_le_versement_ne_bouge_pas(db: _AsyncBridge) -> None:
    """Le cas reel : 3 000 F quittent l'article apporte pour la scolarite."""
    await _deplacer(db)

    imputations = _imputations(db)
    assert FRAIS_RAM not in imputations, "une ligne vidée ne reste pas à zéro"
    assert imputations[FRAIS_SCOLARITE] == Decimal("86000")
    assert imputations[FRAIS_TENUE] == Decimal("18000")

    versement = db._session.get(Payment, VERSEMENT)
    assert versement is not None
    assert versement.amount == Decimal("104000")
    assert versement.status == PaymentStatus.COMPLETED
    assert versement.cancelled_at is None


async def test_les_deux_frais_changent_de_statut(db: _AsyncBridge) -> None:
    """Le frais vide redevient dû, celui qui reçoit avance. Sinon le solde ment."""
    await _deplacer(db)

    ram = db._session.get(EnrollmentFee, FRAIS_RAM)
    scolarite = db._session.get(EnrollmentFee, FRAIS_SCOLARITE)
    assert ram is not None and scolarite is not None
    assert ram.status == EnrollmentFeeStatus.PENDING
    assert scolarite.status == EnrollmentFeeStatus.PARTIAL


async def test_un_deplacement_partiel_laisse_le_reste_en_place(db: _AsyncBridge) -> None:
    await _deplacer(db, montant="1000")

    imputations = _imputations(db)
    assert imputations[FRAIS_RAM] == Decimal("2000")
    assert imputations[FRAIS_SCOLARITE] == Decimal("84000")

    ram = db._session.get(EnrollmentFee, FRAIS_RAM)
    assert ram is not None
    assert ram.status == EnrollmentFeeStatus.PARTIAL


async def test_la_somme_des_imputations_vaut_toujours_le_versement(db: _AsyncBridge) -> None:
    """L'invariant sur lequel repose tout le point par categorie.

    Il tient par construction — on deplace, on ne cree ni ne detruit — et c'est
    exactement le genre de certitude qui cesse d'etre vraie sans qu'on s'en
    apercoive.
    """
    await _deplacer(db, montant="1500")
    assert sum(_imputations(db).values()) == Decimal("104000")


async def test_le_deplacement_vers_un_frais_deja_servi_s_additionne(db: _AsyncBridge) -> None:
    """Jamais deux lignes pour le meme frais : la contrainte unique le refuse."""
    await _deplacer(db, montant="3000")
    lignes = (
        db._session.query(PaymentAllocation)
        .filter(
            PaymentAllocation.payment_id == VERSEMENT,
            PaymentAllocation.enrollment_fee_id == FRAIS_SCOLARITE,
        )
        .all()
    )
    assert len(lignes) == 1


# ---------------------------------------------------------------------------
# Ce que le geste refuse
# ---------------------------------------------------------------------------


async def test_un_versement_annule_ne_se_reimpute_pas(db: _AsyncBridge) -> None:
    """Il ne pose plus d'argent : il n'y a rien a deplacer."""
    versement = db._session.get(Payment, VERSEMENT)
    assert versement is not None
    versement.status = PaymentStatus.CANCELLED
    db._session.flush()

    with pytest.raises(ConflictError, match="encaissé"):
        await _deplacer(db)


async def test_un_versement_en_attente_ne_se_reimpute_pas(db: _AsyncBridge) -> None:
    """Rien n'a bouge : il s'annule et se ressaisit, c'est a cela que sert
    l'annulation."""
    versement = db._session.get(Payment, VERSEMENT)
    assert versement is not None
    versement.status = PaymentStatus.PENDING
    db._session.flush()

    with pytest.raises(ConflictError, match="encaissé"):
        await _deplacer(db)


async def test_on_ne_deplace_pas_plus_qu_il_n_y_a(db: _AsyncBridge) -> None:
    with pytest.raises(BusinessValidationError, match="3000"):
        await _deplacer(db, montant="5000")

    assert _imputations(db)[FRAIS_RAM] == Decimal("3000")


async def test_on_ne_depasse_pas_le_reste_du_frais_d_arrivee(db: _AsyncBridge) -> None:
    """La tenue est soldee : elle n'attend plus rien."""
    with pytest.raises(ConflictError, match="soldé"):
        await _deplacer(db, vers=FRAIS_TENUE)


async def test_un_frais_sans_imputation_sur_ce_versement_est_refuse(db: _AsyncBridge) -> None:
    """Le livret est du, mais ce versement-la ne l'a jamais servi."""
    with pytest.raises(ConflictError, match="n'a rien imputé"):
        await _deplacer(db, depuis=FRAIS_LIVRET, vers=FRAIS_SCOLARITE)


async def test_un_frais_d_une_autre_inscription_est_refuse(db: _AsyncBridge) -> None:
    """Deplacer de l'argent vers le dossier d'une autre famille n'est pas une
    correction d'imputation."""
    ailleurs = EnrollmentFee(
        id=888,
        enrollment_id=INSCRIPTION + 1,
        fee_variant_id=VAR_SCOLARITE,
        fee_category_id=CAT_SCOLARITE,
        amount=Decimal("50000"),
        status=EnrollmentFeeStatus.PENDING,
    )
    db._session.add(ailleurs)
    db._session.flush()

    with pytest.raises(ConflictError, match="n'appartient pas à cette inscription"):
        await _deplacer(db, vers=888)


async def test_le_meme_frais_des_deux_cotes_est_refuse(db: _AsyncBridge) -> None:
    with pytest.raises(BusinessValidationError, match="rien à déplacer"):
        await _deplacer(db, vers=FRAIS_RAM)


async def test_un_motif_court_n_est_pas_un_motif(db: _AsyncBridge) -> None:
    """Meme exigence que l'annulation : une phrase, pas un mot."""
    with pytest.raises(BusinessValidationError, match="motif"):
        await _deplacer(db, motif="erreur")


async def test_un_montant_nul_est_refuse(db: _AsyncBridge) -> None:
    with pytest.raises(BusinessValidationError, match="supérieur à zéro"):
        await _deplacer(db, montant="0")


# ---------------------------------------------------------------------------
# Qui a le droit
# ---------------------------------------------------------------------------


async def test_un_caissier_ne_touche_pas_la_saisie_d_une_autre_caisse(db: _AsyncBridge) -> None:
    with pytest.raises(HTTPException) as exc:
        await _deplacer(db, par=CAISSIER + 1, tout_pouvoir=False)

    assert exc.value.status_code == 403
    assert "autre caisse" in exc.value.detail


async def test_le_refus_nomme_le_geste_refuse(db: _AsyncBridge) -> None:
    """« ce versement ne peut plus etre corrige » laisserait la caissiere
    chercher lequel de ses deux boutons a echoue."""
    with patch(
        "app.repositories.cash_session_repository.is_day_locked",
        new=AsyncMock(return_value=True),
    ):
        with pytest.raises(HTTPException) as exc:
            await _deplacer(db, tout_pouvoir=False)

    assert exc.value.status_code == 409
    assert "réimputé" in exc.value.detail
