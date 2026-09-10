"""L'invariant des allocations, éprouvé sur ses trois formes de rupture.

Le point par catégorie ne lit QUE `payment_allocations` : un versement mal
ventilé en sort sans un mot, pendant que le journal de caisse continue de le
compter. Ce fichier vérifie que la règle qui l'interdit existe pour de bon —
qu'elle refuse à l'écriture, qu'elle retrouve à la lecture, et que les deux
rendent le même verdict sur le même cas.

Ce dernier point est le seul qui compte vraiment à long terme : deux règles
pour une seule question finissent toujours par se contredire, et le jour où
l'audit passe ce que la caisse refuse, on cherche le défaut dans la base au
lieu du code.
"""

from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.exceptions import AllocationInvariantError
from app.models.academic import AcademicYear, Class, Level
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
from app.models.user import Student
from app.services.payments import allocation_invariant

ANNEE = 1
CLASSE = 1
CATEGORIE = 5
VARIANTE = 6
ELEVE = 2
INSCRIPTION = 3
FRAIS_INSCRIPTION = 10
FRAIS_RAMES = 11
CAISSE = 21

#: Le versement sain : 5 000 F reçus, 5 000 F ventilés sur deux frais.
SAIN = 100
#: Ventilé à moitié : 3 000 F reçus, 1 000 F imputés. Les 2 000 F manquants
#: sont au journal de caisse et dans aucun point par catégorie.
INCOMPLET = 101
#: Encaissé, jamais ventilé. Invisible de bout en bout du point par catégorie.
ORPHELIN = 102
#: Ventilé DEUX fois sur le même frais : la somme tombe juste, et rien ne dit
#: pourquoi il y a deux lignes.
EN_DOUBLE = 103
#: Mal ventilé, mais annulé : il n'est compté nulle part, sa ventilation
#: n'engage rien.
ANNULE = 104


class _Pont:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


@compiles(BigInteger, "sqlite")
def _bigint(type_, compiler, **kw):  # noqa: ARG001
    """SQLite n'a pas de BIGINT auto-incrémenté : c'est INTEGER, ou rien."""
    return "INTEGER"


def _versement(ident: int, montant: str, statut: str) -> Payment:
    return Payment(
        id=ident,
        enrollment_id=INSCRIPTION,
        amount=Decimal(montant),
        method=PaymentMethod.CASH.value,
        status=statut,
        received_by=CAISSE,
        created_at=datetime(2026, 10, 5, 9, 30),
        enrollment_fee_id=None,
    )


def _base_d_avant_la_contrainte() -> Engine:
    """Le schéma tel qu'il était AVANT la migration 0079.

    C'est la seule forme sur laquelle l'audit ait quelque chose à trouver : une
    fois `uq_payment_allocation` posée, la base refuse elle-même le doublon. Or
    l'audit existe précisément pour les lignes écrites avant elle — il est
    l'étape 0 du déploiement de cette migration-là, celle qui apprend le
    problème avant la fenêtre plutôt que pendant.

    La contrainte est retirée du modèle le temps du `create_all`, puis remise :
    retaper la table à la main dans ce fichier en ferait un second exemplaire
    du schéma, qui dériverait du premier, et le test finirait par éprouver une
    table qui n'existe nulle part.
    """
    table = PaymentAllocation.__table__
    contrainte = next(c for c in table.constraints if c.name == "uq_payment_allocation")
    table.constraints.discard(contrainte)
    try:
        moteur = create_engine("sqlite://")
        Base.metadata.create_all(moteur)
    finally:
        table.constraints.add(contrainte)
    return moteur


@pytest.fixture()
def db() -> Iterator[Session]:
    """Cinq versements : un sain, trois cassés chacun à sa façon, un annulé."""
    with Session(_base_d_avant_la_contrainte()) as s:
        s.add_all(
            [
                AcademicYear(
                    id=ANNEE,
                    name="2026-2027",
                    start_date=date(2026, 9, 14),
                    end_date=date(2027, 7, 30),
                    is_current=True,
                ),
                Level(id=1, name="6eme"),
                Class(id=CLASSE, name="6eme A", level_id=1),
                Student(id=ELEVE, last_name="KOUASSI", first_name="Aya"),
                Enrollment(
                    id=INSCRIPTION,
                    student_id=ELEVE,
                    class_id=CLASSE,
                    academic_year_id=ANNEE,
                    status=EnrollmentStatus.VALIDE.value,
                ),
                FeeCategory(id=CATEGORIE, name="Inscription", priority=10, is_mandatory=True),
                FeeVariant(
                    id=VARIANTE,
                    fee_category_id=CATEGORIE,
                    academic_year_id=ANNEE,
                    amount=Decimal("30000"),
                ),
                EnrollmentFee(
                    id=FRAIS_INSCRIPTION,
                    enrollment_id=INSCRIPTION,
                    fee_variant_id=VARIANTE,
                    fee_category_id=CATEGORIE,
                    amount=Decimal("30000"),
                    status=EnrollmentFeeStatus.PARTIAL.value,
                ),
            ]
        )
        s.flush()
        s.add_all(
            [
                _versement(SAIN, "5000", PaymentStatus.COMPLETED.value),
                _versement(INCOMPLET, "3000", PaymentStatus.COMPLETED.value),
                _versement(ORPHELIN, "7000", PaymentStatus.COMPLETED.value),
                _versement(EN_DOUBLE, "4000", PaymentStatus.COMPLETED.value),
                _versement(ANNULE, "9000", PaymentStatus.CANCELLED.value),
            ]
        )
        s.flush()
        s.add_all(
            [
                PaymentAllocation(
                    payment_id=SAIN,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("5000"),
                ),
                PaymentAllocation(
                    payment_id=INCOMPLET,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("1000"),
                ),
                # Deux lignes pour le MÊME frais : 2 000 + 2 000 = 4 000, la
                # somme tombe juste et le défaut est ailleurs.
                PaymentAllocation(
                    payment_id=EN_DOUBLE,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("2000"),
                ),
                PaymentAllocation(
                    payment_id=EN_DOUBLE,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("2000"),
                ),
                PaymentAllocation(
                    payment_id=ANNULE,
                    enrollment_fee_id=FRAIS_INSCRIPTION,
                    amount=Decimal("1"),
                ),
            ]
        )
        s.commit()
        yield s


# ---------------------------------------------------------------------------
# La règle, écrite une fois : ce qu'elle accepte et ce qu'elle refuse
# ---------------------------------------------------------------------------


def test_une_ventilation_qui_couvre_le_versement_passe() -> None:
    """Deux frais, deux parts, et la somme y est : rien à signaler."""
    assert (
        allocation_invariant.inspecter(
            Decimal("5000"), [(FRAIS_INSCRIPTION, Decimal("2000")), (FRAIS_RAMES, Decimal("3000"))]
        )
        is None
    )


def test_un_reliquat_non_impute_est_une_rupture() -> None:
    """Les 2 000 F qui manquent seraient encaissés et invisibles par catégorie."""
    rupture = allocation_invariant.inspecter(
        Decimal("3000"), [(FRAIS_INSCRIPTION, Decimal("1000"))]
    )

    assert rupture is not None
    assert rupture.ecart == Decimal("2000")
    assert not rupture.sans_allocation


def test_une_ventilation_qui_deborde_est_une_rupture_aussi() -> None:
    """L'écart compte dans les deux sens : imputer plus que reçu crée de l'argent."""
    rupture = allocation_invariant.inspecter(
        Decimal("1000"), [(FRAIS_INSCRIPTION, Decimal("4000"))]
    )

    assert rupture is not None
    assert rupture.ecart == Decimal("-3000")


def test_un_versement_sans_aucune_allocation_se_dit_comme_tel() -> None:
    """C'est la forme la plus grave, et le message doit la distinguer.

    Un versement qui manque en entier ne se cherche pas au même endroit qu'un
    versement à qui il manque 2 000 F.
    """
    rupture = allocation_invariant.inspecter(Decimal("7000"), [])

    assert rupture is not None
    assert rupture.sans_allocation
    assert "aucun frais" in rupture.message()


def test_deux_lignes_pour_un_meme_frais_sont_refusees_meme_si_la_somme_tombe() -> None:
    """La somme ne voit pas ce cas-là : c'est pour lui que la contrainte existe.

    2 000 + 2 000 = 4 000, le versement est couvert. Mais rien ne dit pourquoi
    il y a deux lignes, ni laquelle annuler le jour d'un remboursement.
    """
    rupture = allocation_invariant.inspecter(
        Decimal("4000"),
        [(FRAIS_INSCRIPTION, Decimal("2000")), (FRAIS_INSCRIPTION, Decimal("2000"))],
    )

    assert rupture is not None
    assert rupture.ecart == Decimal("0")
    assert rupture.frais_en_double == (FRAIS_INSCRIPTION,)


def test_un_demi_centime_ne_declenche_rien() -> None:
    """La tolérance existe pour l'arrondi d'un moteur, pas pour un franc."""
    assert (
        allocation_invariant.inspecter(
            Decimal("3000.00"), [(FRAIS_INSCRIPTION, Decimal("2999.996"))]
        )
        is None
    )
    assert (
        allocation_invariant.inspecter(Decimal("3000.00"), [(FRAIS_INSCRIPTION, Decimal("2999"))])
        is not None
    )


# ---------------------------------------------------------------------------
# La vérification à l'écriture
# ---------------------------------------------------------------------------


def test_verifier_laisse_passer_une_ventilation_saine() -> None:
    """Aucune exception : le cas normal ne doit rien coûter à la caisse."""
    allocation_invariant.verifier(
        Decimal("5000"), [(FRAIS_INSCRIPTION, Decimal("2000")), (FRAIS_RAMES, Decimal("3000"))]
    )


def test_verifier_refuse_et_dit_que_ce_n_est_pas_une_erreur_de_saisie() -> None:
    """La caissière a tapé un montant juste ; l'envoyer le corriger serait faux.

    Le code machine est distinct de celui d'une validation ordinaire : c'est ce
    qui permet à l'écran de dire autre chose que « corrigez votre saisie », et
    au journal de distinguer ce défaut-ci d'un vrai refus de saisie.
    """
    with pytest.raises(AllocationInvariantError) as leve:
        allocation_invariant.verifier(Decimal("3000"), [(FRAIS_INSCRIPTION, Decimal("1000"))])

    assert leve.value.code == "ALLOCATION_INVARIANT"
    assert "n'a pas été enregistré" in leve.value.detail
    assert "erreur de saisie" in leve.value.detail


# ---------------------------------------------------------------------------
# Le contrôle a posteriori, sur une vraie base
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_audit_retrouve_les_trois_formes_de_rupture(db: Session) -> None:
    """Incomplet, orphelin, en double : les trois sortent, le sain non."""
    ruptures = await allocation_invariant.auditer(_Pont(db))

    assert {rupture.payment_id for rupture in ruptures} == {INCOMPLET, ORPHELIN, EN_DOUBLE}


@pytest.mark.asyncio
async def test_l_audit_ignore_un_versement_annule(db: Session) -> None:
    """Un versement annulé n'est compté nulle part : sa ventilation n'engage rien.

    Le signaler ferait remonter à chaque passage des versements dont personne
    n'a rien à faire — et un contrôle qui crie pour rien cesse d'être lu.
    """
    ruptures = await allocation_invariant.auditer(_Pont(db))

    assert ANNULE not in {rupture.payment_id for rupture in ruptures}


@pytest.mark.asyncio
async def test_l_audit_nomme_le_frais_impute_deux_fois(db: Session) -> None:
    """Nommer le frais, pas seulement le versement : c'est là qu'on va regarder."""
    ruptures = await allocation_invariant.auditer(_Pont(db))
    double = next(rupture for rupture in ruptures if rupture.payment_id == EN_DOUBLE)

    assert double.frais_en_double == (FRAIS_INSCRIPTION,)
    assert "plusieurs fois" in double.message()


@pytest.mark.asyncio
async def test_l_audit_chiffre_ce_qui_manque(db: Session) -> None:
    """Un audit qui dirait « quelque chose cloche » sans le montant n'aide pas."""
    ruptures = await allocation_invariant.auditer(_Pont(db))
    incomplet = next(rupture for rupture in ruptures if rupture.payment_id == INCOMPLET)
    orphelin = next(rupture for rupture in ruptures if rupture.payment_id == ORPHELIN)

    assert incomplet.montant == Decimal("3000")
    assert incomplet.alloue == Decimal("1000")
    assert incomplet.ecart == Decimal("2000")
    assert orphelin.sans_allocation


@pytest.mark.asyncio
async def test_l_audit_et_la_caisse_rendent_le_meme_verdict(db: Session) -> None:
    """Une seule règle pour une seule question, sur exactement le même cas.

    Si les deux jugements divergeaient, l'audit passerait un jour ce que la
    caisse refuse — et on chercherait le défaut dans la base au lieu du code.
    """
    ruptures = await allocation_invariant.auditer(_Pont(db))
    assert ruptures

    for rupture in ruptures:
        # La ventilation telle qu'elle est en base pour ce versement-là.
        ventilation = db.execute(
            select(PaymentAllocation.enrollment_fee_id, PaymentAllocation.amount).where(
                PaymentAllocation.payment_id == rupture.payment_id
            )
        ).all()
        with pytest.raises(AllocationInvariantError):
            allocation_invariant.verifier(
                rupture.montant, [(int(frais), part) for frais, part in ventilation]
            )
