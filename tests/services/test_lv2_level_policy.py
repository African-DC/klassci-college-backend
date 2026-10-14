"""Politique LV2 multi-tenant : ni nom affiché ni cache global.

Ces tests empruntent les mêmes requêtes SQL que l'API, sur deux bases
distinctes. Le classement pédagogique peut être renommé sans changer la règle.
"""

from collections.abc import Iterator
from importlib import util as import_util
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessValidationError
from app.models.academic import Level
from app.services.lv2_policy import ensure_lv2_allowed, lv2_allowed_for_class
from tests.services._sheet_world import (
    CLASSE_3E, CLASSE_4E, CLASSE_5E, CLASSE_6E,
    AsyncBridge, build_school,
)


@pytest.fixture()
def tenant() -> Iterator[Session]:
    yield from build_school()


@pytest.mark.asyncio
async def test_regle_actuelle_par_defaut(tenant: Session) -> None:
    db = AsyncBridge(tenant)
    assert not await lv2_allowed_for_class(db, CLASSE_6E)
    assert not await lv2_allowed_for_class(db, CLASSE_5E)
    assert await lv2_allowed_for_class(db, CLASSE_4E)
    assert await lv2_allowed_for_class(db, CLASSE_3E)
    with pytest.raises(BusinessValidationError):
        await ensure_lv2_allowed(db, CLASSE_5E, "allemand")
    await ensure_lv2_allowed(db, CLASSE_5E, None)


@pytest.mark.asyncio
async def test_regle_personnalisable_independante_du_nom(tenant: Session) -> None:
    sixieme = tenant.get(Level, 1)
    quatrieme = tenant.get(Level, 3)
    assert sixieme is not None and quatrieme is not None
    sixieme.name = "Section découverte"
    sixieme.lv2_enabled = True
    quatrieme.name = "Niveau avancé"
    quatrieme.lv2_enabled = False
    tenant.commit()

    db = AsyncBridge(tenant)
    assert await lv2_allowed_for_class(db, CLASSE_6E)
    assert not await lv2_allowed_for_class(db, CLASSE_4E)
    await ensure_lv2_allowed(db, CLASSE_6E, "espagnol")
    with pytest.raises(BusinessValidationError):
        await ensure_lv2_allowed(db, CLASSE_4E, "allemand")


@pytest.mark.asyncio
async def test_aucune_fuite_entre_deux_etablissements(tenant: Session) -> None:
    with next(build_school()) as second_tenant:
        first = tenant.get(Level, 1)
        assert first is not None
        first.lv2_enabled = True
        tenant.commit()

        assert await lv2_allowed_for_class(AsyncBridge(tenant), CLASSE_6E)
        assert not await lv2_allowed_for_class(AsyncBridge(second_tenant), CLASSE_6E)


def test_migration_initialise_les_anciens_libelles_une_seule_fois() -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261014_0086_lv2_level_policy.py"
    spec = import_util.spec_from_file_location("migration_lv2_0086", path)
    assert spec is not None and spec.loader is not None
    mod = import_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._was_forbidden("6ème")
    assert mod._was_forbidden("Sixième")
    assert mod._was_forbidden("5eme")
    assert mod._was_forbidden("Cinquième")
    assert not mod._was_forbidden("4ème")
    assert not mod._was_forbidden("Niveau personnalisé")
