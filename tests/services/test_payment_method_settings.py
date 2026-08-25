"""L'écran de paramètres : retirer les espèces au comptable, sans rien casser d'autre.

L'écran écrit dans `role_permissions`, la même table que la grille des
permissions. Il n'y a donc qu'une vérité, lisible de deux façons, et non deux
réglages qui peuvent se contredire. La contrepartie est qu'il doit toucher
UNIQUEMENT les slugs `payments:method:*` : sans quoi cette page deviendrait un
moyen détourné de modifier des droits qu'elle ne montre pas.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.database import Base
from app.core.payment_methods import SELECTABLE_METHODS
from app.schemas.payment_method_settings import (
    PaymentMethodRoleUpdate,
    PaymentMethodSettingsUpdate,
)
from app.services import payment_method_settings as service

_TABLES = ("roles", "permissions", "role_permissions")


def _create_audit_table(engine: Any) -> None:
    """Le journal d'audit, avec une clé primaire que SQLite sait incrémenter.

    En production la colonne est un `BIGINT AUTO_INCREMENT` ; SQLite ne
    numérote automatiquement que les `INTEGER PRIMARY KEY`. On ne change que
    le type de la copie utilisée pour créer la table de test : le SQL
    d'insertion exercé reste celui de `audit_log`.
    """
    from sqlalchemy import Integer, MetaData

    copie = AuditLog.__table__.to_metadata(MetaData())
    copie.c.id.type = Integer()
    copie.create(engine)


ROLE_COMPTABLE, ROLE_CAISSIER, ROLE_PROF = 21, 22, 23
PERM_CREATE, PERM_CANCEL = 90, 91


class _AsyncBridge:
    """Une `AsyncSession` de façade au-dessus d'une session synchrone."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.flush()

    def begin_nested(self) -> Any:
        return _NoopTransaction()


class _NoopTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.fixture
def db() -> Iterator[tuple[Any, Session]]:
    """Deux profils qui encaissent, un qui n'encaisse pas, droits par défaut."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[n] for n in _TABLES])
    _create_audit_table(engine)

    with Session(engine) as session:
        now = datetime(2026, 8, 21, 9, 0)
        session.execute(
            insert(Base.metadata.tables["roles"]),
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
                {
                    "id": ROLE_PROF,
                    "name": "teacher",
                    "description": "Enseignant",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        perms: list[dict[str, Any]] = [
            {"id": 100 + i, "slug": f"payments:method:{m}", "name": m}
            for i, m in enumerate(SELECTABLE_METHODS)
        ]
        perms += [
            {"id": PERM_CREATE, "slug": "payments:create", "name": "Create payments"},
            {"id": PERM_CANCEL, "slug": "payments:cancel:any", "name": "Cancel"},
        ]
        session.execute(insert(Base.metadata.tables["permissions"]), perms)

        links = []
        for role_id in (ROLE_COMPTABLE, ROLE_CAISSIER):
            links += [{"role_id": role_id, "permission_id": p["id"]} for p in perms]
        # L'enseignant n'encaisse pas : il n'a aucun de ces droits.
        session.execute(insert(Base.metadata.tables["role_permissions"]), links)
        session.flush()
        yield _AsyncBridge(session), session

    engine.dispose()


@pytest.mark.asyncio
async def test_lecran_ne_liste_que_les_profils_qui_encaissent(
    db: tuple[Any, Session],
) -> None:
    bridge, _session = db
    settings = await service.get_settings(bridge)

    assert {r.role_name for r in settings.roles} == {"accountant", "cashier"}
    assert [m.key for m in settings.methods] == list(SELECTABLE_METHODS)
    # L'écran doit pouvoir avertir que les espèces engagent une caisse.
    assert [m.key for m in settings.methods if m.requires_cash_drawer] == ["cash"]


@pytest.mark.asyncio
async def test_lecran_affiche_les_libelles_lisibles_des_profils(
    db: tuple[Any, Session],
) -> None:
    bridge, _session = db
    settings = await service.get_settings(bridge)
    labels = {r.role_name: r.role_label for r in settings.roles}
    assert labels["accountant"] == "Comptable / Trésorier"


@pytest.mark.asyncio
async def test_retirer_les_especes_au_comptable(db: tuple[Any, Session]) -> None:
    bridge, _session = db
    sans_especes = [m for m in SELECTABLE_METHODS if m != "cash"]

    after = await service.update_settings(
        bridge,
        PaymentMethodSettingsUpdate(
            roles=[PaymentMethodRoleUpdate(role_id=ROLE_COMPTABLE, allowed_methods=sans_especes)]
        ),
        updated_by=1,
    )

    par_role = {r.role_name: r.allowed_methods for r in after.roles}
    assert par_role["accountant"] == sans_especes
    assert par_role["cashier"] == list(SELECTABLE_METHODS), "le guichet ne bouge pas"


@pytest.mark.asyncio
async def test_lecran_ne_touche_a_aucun_autre_droit(db: tuple[Any, Session]) -> None:
    """Retirer un moyen ne doit pas retirer `payments:create` au passage."""
    bridge, session = db

    await service.update_settings(
        bridge,
        PaymentMethodSettingsUpdate(
            roles=[PaymentMethodRoleUpdate(role_id=ROLE_COMPTABLE, allowed_methods=["wave"])]
        ),
        updated_by=1,
    )

    rp = Base.metadata.tables["role_permissions"]
    restants = {
        row[0]
        for row in session.execute(
            rp.select().with_only_columns(rp.c.permission_id).where(rp.c.role_id == ROLE_COMPTABLE)
        ).all()
    }
    assert PERM_CREATE in restants, "le comptable doit toujours pouvoir encaisser"
    assert PERM_CANCEL in restants, "les droits hors moyens de paiement sont intacts"


@pytest.mark.asyncio
async def test_reautoriser_un_moyen_le_remet(db: tuple[Any, Session]) -> None:
    """Décocher puis recocher doit revenir exactement à l'état de départ."""
    bridge, _session = db

    await service.update_settings(
        bridge,
        PaymentMethodSettingsUpdate(
            roles=[PaymentMethodRoleUpdate(role_id=ROLE_COMPTABLE, allowed_methods=["wave"])]
        ),
        updated_by=1,
    )
    after = await service.update_settings(
        bridge,
        PaymentMethodSettingsUpdate(
            roles=[
                PaymentMethodRoleUpdate(
                    role_id=ROLE_COMPTABLE, allowed_methods=list(SELECTABLE_METHODS)
                )
            ]
        ),
        updated_by=1,
    )

    par_role = {r.role_name: r.allowed_methods for r in after.roles}
    assert par_role["accountant"] == list(SELECTABLE_METHODS)


@pytest.mark.asyncio
async def test_un_moyen_inconnu_est_refuse(db: tuple[Any, Session]) -> None:
    from app.core.exceptions import BusinessValidationError

    bridge, _session = db
    with pytest.raises(BusinessValidationError):
        await service.update_settings(
            bridge,
            PaymentMethodSettingsUpdate(
                roles=[PaymentMethodRoleUpdate(role_id=ROLE_COMPTABLE, allowed_methods=["bitcoin"])]
            ),
            updated_by=1,
        )


@pytest.mark.asyncio
async def test_un_profil_qui_nencaisse_pas_nest_pas_configurable(
    db: tuple[Any, Session],
) -> None:
    """Régler les moyens de paiement d'un enseignant n'a pas de sens."""
    from app.core.exceptions import NotFoundError

    bridge, _session = db
    with pytest.raises(NotFoundError):
        await service.update_settings(
            bridge,
            PaymentMethodSettingsUpdate(
                roles=[PaymentMethodRoleUpdate(role_id=ROLE_PROF, allowed_methods=["cash"])]
            ),
            updated_by=1,
        )


@pytest.mark.asyncio
async def test_le_changement_laisse_une_trace_dans_laudit(
    db: tuple[Any, Session],
) -> None:
    """Qui peut encaisser des espèces est exactement ce qu'un auditeur relit."""
    bridge, session = db

    await service.update_settings(
        bridge,
        PaymentMethodSettingsUpdate(
            roles=[PaymentMethodRoleUpdate(role_id=ROLE_COMPTABLE, allowed_methods=["wave"])]
        ),
        updated_by=1,
    )

    entries = session.execute(
        AuditLog.__table__.select().where(AuditLog.entity_type == "role")
    ).all()
    assert len(entries) == 1
