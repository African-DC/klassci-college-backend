"""Règle LV2 en base tenant : code par ID, indépendamment du nom affiché."""
import pytest
from app.models.academic import Level
from app.core.exceptions import BusinessValidationError
from app.services.enrollment_profile import ensure_lv2_allowed
from tests.services._sheet_world import CLASSE_6E, CLASSE_4E, AsyncBridge, build_school

@pytest.mark.asyncio
async def test_default_legacy_and_tenant_override() -> None:
    for db in build_school():
        bridge = AsyncBridge(db)
        with pytest.raises(BusinessValidationError):
            await ensure_lv2_allowed(bridge, CLASSE_6E, "espagnol")
        assert await ensure_lv2_allowed(bridge, CLASSE_4E, "allemand") is True
        sixieme = db.get(Level, 1)
        sixieme.lv2_enabled = True
        sixieme.name = "Cycle découverte"
        db.commit()
        assert await ensure_lv2_allowed(bridge, CLASSE_6E, "espagnol") is True
        quatrieme = db.get(Level, 3)
        quatrieme.lv2_enabled = False
        db.commit()
        with pytest.raises(BusinessValidationError):
            await ensure_lv2_allowed(bridge, CLASSE_4E, "allemand")
        # Un champ explicitement effacé reste toujours accepté.
        assert await ensure_lv2_allowed(bridge, CLASSE_4E, None) is False

@pytest.mark.asyncio
async def test_tenant_settings_are_database_local() -> None:
    # Deux bases SQLite distinctes simulent deux tenants, sans cache global.
    worlds = [build_school(), build_school()]
    try:
        a = next(worlds[0]); b = next(worlds[1])
        a.get(Level, 1).lv2_enabled = True
        a.commit()
        assert await ensure_lv2_allowed(AsyncBridge(a), CLASSE_6E, "allemand") is True
        with pytest.raises(BusinessValidationError):
            await ensure_lv2_allowed(AsyncBridge(b), CLASSE_6E, "allemand")
    finally:
        for world in worlds:
            world.close()
