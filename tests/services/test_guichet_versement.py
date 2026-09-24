"""Le guichet : pas de validation sans versement, et pas de versement en double.

Deux règles, décidées le 2026-09-24 après lecture de la prod : 701 inscriptions
validées une dizaine de secondes après leur création, avant tout versement ; et
aucun garde-fou contre un second envoi quand la 3G coupe au moment
d'enregistrer.

Ces tests exécutent les vraies requêtes sur une base SQLite montée depuis le
schéma du modèle, et regardent ce qui est refusé, rendu ou écrit.
"""

from collections.abc import Iterator
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, MetaData, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.dependencies import TokenData
from app.core.exceptions import BusinessValidationError
from app.models.fee import Payment
from app.schemas.payment import EnrollmentPaymentCreate
from app.services import enrollment_validation
from app.services.payments import recording
from app.services.payments._replay import versement_deja_ecrit

INSCRIPTION = 42
AUTRE_INSCRIPTION = 43
FRAIS = 10
CLE = "envoi-0001-aaaa"
ACTEUR = TokenData(user_id=7, tenant_id="local", email="caisse@college.ci")


class _AsyncBridge:
    """L'allure d'une `AsyncSession` sur une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    async def rollback(self) -> None:
        self._session.rollback()

    async def commit(self) -> None:
        self._session.commit()


def _valeur_factice(colonne: Any) -> Any:
    enum = getattr(colonne.type, "enum_class", None) or getattr(
        getattr(colonne.type, "impl", None), "enum_class", None
    )
    if enum is not None:
        return next(iter(enum)).value
    try:
        type_python = colonne.type.python_type
    except NotImplementedError:
        return "x"
    return {
        int: 1,
        str: "x",
        bool: False,
        Decimal: Decimal("0"),
        date: date(2026, 9, 1),
        datetime: datetime(2026, 9, 1, 8, 0),
        time: time(8, 0),
    }.get(type_python, "x")


def _inserer(engine: Engine, miroir: MetaData, table: str, **valeurs: Any) -> None:
    t = miroir.tables[table]
    for colonne in t.columns:
        manquante = colonne.name not in valeurs and not colonne.nullable
        sans_defaut = colonne.default is None and colonne.server_default is None
        if manquante and sans_defaut and not colonne.primary_key:
            valeurs[colonne.name] = _valeur_factice(colonne)
    with engine.begin() as conn:
        conn.execute(t.insert().values(**valeurs))


@pytest.fixture
def base() -> Iterator[tuple[_AsyncBridge, Engine, MetaData]]:
    """Une inscription qui doit 25 000 FCFA d'inscription, sans aucun versement."""
    miroir = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(miroir)
    engine = create_engine("sqlite://")
    miroir.create_all(engine)

    _inserer(engine, miroir, "fee_categories", id=1, name="Inscription", priority=10)
    _inserer(engine, miroir, "fee_variants", id=1, fee_category_id=1, amount=Decimal("25000"))
    for eleve, inscription in ((5, INSCRIPTION), (6, AUTRE_INSCRIPTION)):
        _inserer(engine, miroir, "students", id=eleve, first_name="Aminata", last_name="Traoré")
        _inserer(
            engine,
            miroir,
            "enrollments",
            id=inscription,
            student_id=eleve,
            status="prospect",
            archived_at=None,
        )
    _inserer(
        engine,
        miroir,
        "enrollment_fees",
        id=FRAIS,
        enrollment_id=INSCRIPTION,
        fee_variant_id=1,
        fee_category_id=1,
        amount=Decimal("25000"),
        status="pending",
    )
    with Session(engine) as session:
        yield _AsyncBridge(session), engine, miroir


def _versement(
    engine: Engine, miroir: MetaData, *, pid: int, statut: str = "completed", cle: str | None = None
) -> None:
    _inserer(
        engine,
        miroir,
        "payments",
        id=pid,
        enrollment_id=INSCRIPTION,
        amount=Decimal("25000"),
        method="cash",
        status=statut,
        idempotency_key=cle,
    )


# -- Pas de validation sans versement ----------------------------------------


@pytest.mark.asyncio
async def test_une_inscription_sans_versement_ne_se_valide_pas(base: Any) -> None:
    db, _, _ = base
    with pytest.raises(BusinessValidationError) as refus:
        await enrollment_validation.ensure_payment_received(db, INSCRIPTION)
    assert "Encaissez d'abord un versement" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_un_versement_recu_ouvre_la_validation(base: Any) -> None:
    db, engine, miroir = base
    _versement(engine, miroir, pid=100)
    await enrollment_validation.ensure_payment_received(db, INSCRIPTION)


@pytest.mark.asyncio
async def test_un_versement_annule_ne_compte_pas(base: Any) -> None:
    """L'argent est reparti : le dossier n'a plus rien reçu."""
    db, engine, miroir = base
    _versement(engine, miroir, pid=100, statut="cancelled")
    with pytest.raises(BusinessValidationError):
        await enrollment_validation.ensure_payment_received(db, INSCRIPTION)


@pytest.mark.asyncio
async def test_une_inscription_sans_rien_a_regler_en_argent_se_valide(base: Any) -> None:
    """Un boursier exonéré n'a rien à verser : l'exiger bloquerait son dossier."""
    db, engine, _ = base
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE enrollment_fees SET status = 'waived'")
    await enrollment_validation.ensure_payment_received(db, INSCRIPTION)


@pytest.mark.asyncio
async def test_l_ecran_lit_la_regle_de_la_garde_telle_quelle(base: Any) -> None:
    """Sans versement mais sans rien à régler en argent, l'inscription
    n'attend rien : l'écran doit proposer « Valider », pas « Encaisser »."""
    db, engine, _ = base
    assert await enrollment_validation.awaiting_payment(db, [INSCRIPTION]) == {INSCRIPTION}
    with engine.begin() as conn:
        conn.exec_driver_sql("UPDATE enrollment_fees SET status = 'waived'")
    assert await enrollment_validation.awaiting_payment(db, [INSCRIPTION]) == set()


@pytest.mark.asyncio
async def test_une_inscription_qui_a_recu_un_versement_n_attend_plus_rien(base: Any) -> None:
    db, engine, miroir = base
    _versement(engine, miroir, pid=100)
    assert await enrollment_validation.awaiting_payment(db, [INSCRIPTION]) == set()


@pytest.mark.asyncio
async def test_la_liste_dit_quelles_inscriptions_ont_recu_un_versement(base: Any) -> None:
    db, engine, miroir = base
    _versement(engine, miroir, pid=100)
    assert await enrollment_validation.enrollments_with_payment(
        db, [INSCRIPTION, AUTRE_INSCRIPTION]
    ) == {INSCRIPTION}


# -- Pas de versement en double -----------------------------------------------


def _envoi(montant: str = "25000", cle: str = CLE) -> EnrollmentPaymentCreate:
    return EnrollmentPaymentCreate(amount=Decimal(montant), method="cash", idempotency_key=cle)


@pytest.mark.asyncio
async def test_une_cle_deja_vue_rend_le_versement_deja_ecrit(base: Any) -> None:
    db, engine, miroir = base
    _versement(engine, miroir, pid=100, cle=CLE)
    rendu = await versement_deja_ecrit(db, INSCRIPTION, _envoi())
    assert rendu is not None
    assert rendu.id == 100
    # Le reste vient de la base, pas d'une soustraction faite par l'écran :
    # rejouer un envoi ne décompte pas le versement une seconde fois.
    assert rendu.enrollment_remaining_after == 25000.0


@pytest.mark.asyncio
async def test_une_cle_neuve_ne_rend_rien(base: Any) -> None:
    db, _, _ = base
    assert await versement_deja_ecrit(db, INSCRIPTION, _envoi()) is None


@pytest.mark.asyncio
async def test_une_cle_reprise_pour_un_autre_montant_est_refusee(base: Any) -> None:
    """Rendre ce reçu-là pour 10 000 FCFA mentirait à la caissière."""
    db, engine, miroir = base
    _versement(engine, miroir, pid=100, cle=CLE)
    with pytest.raises(BusinessValidationError):
        await versement_deja_ecrit(db, INSCRIPTION, _envoi("10000"))


def test_la_base_refuse_deux_versements_sous_la_meme_cle(base: Any) -> None:
    _, engine, miroir = base
    _versement(engine, miroir, pid=100, cle=CLE)
    with pytest.raises(IntegrityError):
        _versement(engine, miroir, pid=101, cle=CLE)


@pytest.mark.asyncio
async def test_deux_envois_simultanes_ne_font_qu_un_versement(
    base: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le second envoi arrive pendant que le premier écrit. Les deux passent
    la vérification de clé ; la contrainte d'unicité arrête le second, qui
    rend alors le versement du premier au lieu d'une erreur."""
    db, engine, miroir = base

    async def _rien(*_a: object, **_k: object) -> None:
        return None

    async def _le_premier_a_gagne(*_a: object, **_k: object) -> object:
        _versement(engine, miroir, pid=100, cle=CLE)
        raise IntegrityError("INSERT", {}, Exception("Duplicate entry"))

    monkeypatch.setattr(recording, "_guard_method_and_drawer", _rien)
    monkeypatch.setattr(recording, "_ecrire_versement", _le_premier_a_gagne)

    rendu = await recording.record_enrollment_payment(db, INSCRIPTION, _envoi(), actor=ACTEUR)

    assert rendu.id == 100
    with Session(engine) as lecture:
        assert lecture.scalar(select(func.count()).select_from(Payment)) == 1
