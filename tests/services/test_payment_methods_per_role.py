"""Qui peut encaisser par quel moyen, et ce qu'on répond quand ce n'est pas le cas.

Le comptable du collège Rostan encaisse en Wave, MTN MoMo, Orange Money, Moov
Money, virement et chèque. Jamais en espèces : il n'a pas de tiroir, et les
espèces en imposent un.

Ces tests font tourner le vrai SQL sur SQLite, comme `test_money_single_truth`,
plutôt que de simuler la matrice rôle/permission — c'est précisément la matrice
qu'on veut vérifier.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.dependencies import TokenData
from app.core.exceptions import PaymentMethodNotAllowedError
from app.core.payment_methods import SELECTABLE_METHODS
from app.models.academic import SchoolSettings
from app.models.permission import Permission, Role, RolePermission, UserRole
from app.services.payments import methods as payment_methods

_TABLES = ("roles", "permissions", "role_permissions", "user_roles", "school_settings")

COMPTABLE, CAISSIERE, SANS_ROLE = 11, 12, 13
ROLE_COMPTABLE, ROLE_CAISSIER = 21, 22
PERM_CASH = 100 + SELECTABLE_METHODS.index("cash")


class _AsyncBridge:
    """Donne l'allure d'une `AsyncSession` à une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]


def _token(user_id: int) -> TokenData:
    return TokenData(user_id=user_id, tenant_id="local", email=f"u{user_id}@college.ci")


@pytest.fixture
def db() -> Iterator[tuple[Any, Session]]:
    """Un établissement avec un comptable et une caissière, droits par défaut.

    Les défauts reproduisent l'existant : les deux profils encaissent par les
    sept moyens, comme avant que ces droits n'existent.
    """
    engine = create_engine("sqlite://")
    tables = [Base.metadata.tables[name] for name in _TABLES]
    Base.metadata.create_all(engine, tables=tables)

    with Session(engine) as session:
        now = datetime(2026, 8, 21, 9, 0)
        session.execute(
            insert(Role),
            [
                {
                    "id": ROLE_COMPTABLE,
                    "name": "accountant",
                    "description": "Comptable / Trésorier",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": ROLE_CAISSIER,
                    "name": "cashier",
                    "description": "Caissier / Caissière",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        perms: list[dict[str, Any]] = [
            {"id": 100 + i, "slug": f"payments:method:{m}", "name": m}
            for i, m in enumerate(SELECTABLE_METHODS)
        ]
        perms.append({"id": 90, "slug": "payments:create", "name": "Create payments"})
        session.execute(insert(Permission), perms)

        for role_id in (ROLE_COMPTABLE, ROLE_CAISSIER):
            session.execute(
                insert(RolePermission),
                [{"role_id": role_id, "permission_id": p["id"]} for p in perms],
            )
        session.execute(
            insert(UserRole),
            [
                {
                    "id": 1,
                    "user_id": COMPTABLE,
                    "role_id": ROLE_COMPTABLE,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": 2,
                    "user_id": CAISSIERE,
                    "role_id": ROLE_CAISSIER,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        session.flush()
        yield _AsyncBridge(session), session

    engine.dispose()


def _decocher_especes(session: Session, role_id: int) -> None:
    """Ce que fait l'écran de paramètres quand on décoche « Espèces »."""
    session.execute(
        RolePermission.__table__.delete().where(
            RolePermission.role_id == role_id,
            RolePermission.permission_id == PERM_CASH,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Le cas de l'école : un comptable sans espèces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_comptable_sans_especes_se_voit_refuser_un_versement_en_especes(
    db: tuple[Any, Session],
) -> None:
    bridge, session = db
    _decocher_especes(session, ROLE_COMPTABLE)

    with pytest.raises(PaymentMethodNotAllowedError) as excinfo:
        await payment_methods.ensure_method_allowed(bridge, _token(COMPTABLE), "cash")

    assert excinfo.value.status_code == 403
    detail = excinfo.value.detail
    # Le refus nomme le moyen refusé, dit ce que la personne PEUT faire, et
    # vers qui l'envoyer. Un « Permission denied » ne ferait rien de tout ça.
    assert "Espèces" in detail
    assert "Wave" in detail, "le refus doit rappeler ce que le comptable peut encaisser"
    assert "Caissier / Caissière" in detail, "il doit dire à qui s'adresser"


@pytest.mark.asyncio
async def test_le_meme_comptable_encaisse_un_virement_sans_difficulte(
    db: tuple[Any, Session],
) -> None:
    bridge, session = db
    _decocher_especes(session, ROLE_COMPTABLE)

    # Ne lève pas : c'est tout ce qu'on lui demande.
    await payment_methods.ensure_method_allowed(bridge, _token(COMPTABLE), "bank_transfer")

    allowed = await payment_methods.allowed_methods_for(bridge, _token(COMPTABLE))
    assert allowed == [
        "wave",
        "mtn_momo",
        "orange_money",
        "moov_money",
        "bank_transfer",
        "cheque",
    ]


@pytest.mark.asyncio
async def test_la_caissiere_garde_tous_ses_moyens(db: tuple[Any, Session]) -> None:
    """Retirer les espèces au comptable ne doit rien changer au guichet."""
    bridge, session = db
    _decocher_especes(session, ROLE_COMPTABLE)

    assert await payment_methods.allowed_methods_for(bridge, _token(CAISSIERE)) == list(
        SELECTABLE_METHODS
    )
    await payment_methods.ensure_method_allowed(bridge, _token(CAISSIERE), "cash")


@pytest.mark.asyncio
async def test_une_ecole_qui_na_rien_configure_se_comporte_comme_avant(
    db: tuple[Any, Session],
) -> None:
    """Aucun `school_settings`, droits par défaut : les sept moyens passent."""
    bridge, _session = db

    for method in SELECTABLE_METHODS:
        await payment_methods.ensure_method_allowed(bridge, _token(COMPTABLE), method)

    assert await payment_methods.allowed_methods_for(bridge, _token(COMPTABLE)) == list(
        SELECTABLE_METHODS
    )


# ---------------------------------------------------------------------------
# Les deux filtres se composent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_letablissement_prime_sur_le_role(db: tuple[Any, Session]) -> None:
    """Un moyen que l'école n'accepte pas ne passe pour personne."""
    bridge, session = db
    now = datetime(2026, 8, 21, 9, 0)
    session.execute(
        insert(SchoolSettings).values(
            id=1,
            school_name="Collège Rostan",
            enabled_payment_methods="cash,wave",
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()

    assert await payment_methods.allowed_methods_for(bridge, _token(CAISSIERE)) == [
        "cash",
        "wave",
    ]

    with pytest.raises(PaymentMethodNotAllowedError) as excinfo:
        await payment_methods.ensure_method_allowed(bridge, _token(CAISSIERE), "cheque")
    assert "établissement n'accepte pas" in excinfo.value.detail


@pytest.mark.asyncio
async def test_un_utilisateur_sans_role_ne_peut_rien_encaisser(
    db: tuple[Any, Session],
) -> None:
    bridge, _session = db
    assert await payment_methods.allowed_methods_for(bridge, _token(SANS_ROLE)) == []


# ---------------------------------------------------------------------------
# La valeur historique
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mobile_money_ne_peut_plus_etre_saisi_et_le_dit(
    db: tuple[Any, Session],
) -> None:
    """Refus explicite plutôt que « moyen inconnu » : la valeur a bien existé."""
    bridge, _session = db

    with pytest.raises(PaymentMethodNotAllowedError) as excinfo:
        await payment_methods.ensure_method_allowed(bridge, _token(CAISSIERE), "mobile_money")

    assert "historique" in excinfo.value.detail
    assert "Mobile Money" in excinfo.value.detail


@pytest.mark.asyncio
async def test_mobile_money_nest_jamais_propose_au_selecteur(
    db: tuple[Any, Session],
) -> None:
    bridge, _session = db
    assert "mobile_money" not in await payment_methods.allowed_methods_for(
        bridge, _token(CAISSIERE)
    )
