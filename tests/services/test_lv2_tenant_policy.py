"""Disponibilite LV2 : bases tenant independantes, valeurs historiques et changement de niveau."""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.models.academic import Level
from app.models.enrollment import Enrollment
from app.schemas.admin import ClassUpdate, LevelUpdate
from app.services import admin_service
from app.services.enrollment_profile import lv2_enabled_for_class
from tests.services._sheet_world import (
    ACTEUR, AN_COURANT, CLASSE_4E, CLASSE_6E,
    AsyncBridge, add_enrollment, add_student, build_school,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    yield from build_school()


@pytest.mark.asyncio
async def test_configuration_isolee_par_base_tenant() -> None:
    first = build_school()
    second = build_school()
    a = next(first)
    b = next(second)
    try:
        assert not await lv2_enabled_for_class(AsyncBridge(a), CLASSE_6E)
        assert not await lv2_enabled_for_class(AsyncBridge(b), CLASSE_6E)
        await admin_service.update_level(
            AsyncBridge(a), 1, LevelUpdate(lv2_enabled=True), updated_by=ACTEUR,
        )
        assert await lv2_enabled_for_class(AsyncBridge(a), CLASSE_6E)
        assert not await lv2_enabled_for_class(AsyncBridge(b), CLASSE_6E)
        assert a.get(Level, 1).lv2_enabled is True
        assert b.get(Level, 1).lv2_enabled is False
    finally:
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_deplacer_la_classe_vers_niveau_sans_lv2_retire_et_audite(db: Session) -> None:
    add_student(db, 100, "Bamba", "Aya")
    enrollment = add_enrollment(
        db, 100, 100, CLASSE_4E, AN_COURANT, lv2="allemand",
    )
    db.commit()
    await admin_service.update_class(
        AsyncBridge(db), CLASSE_4E, ClassUpdate(level_id=1), updated_by=ACTEUR,
    )
    db.refresh(enrollment)
    assert enrollment.lv2 is None
    audit = (
        db.query(AuditLog)
        .filter_by(entity_type="enrollment", entity_id=enrollment.id)
        .one()
    )
    assert audit.old_values == {"lv2": "allemand"}
    assert audit.new_values == {"lv2": None}


@pytest.mark.asyncio
async def test_desactiver_un_niveau_ne_supprime_pas_les_lv2_historiques(db: Session) -> None:
    add_student(db, 100, "Bamba", "Aya")
    enrollment = add_enrollment(
        db, 100, 100, CLASSE_4E, AN_COURANT, lv2="espagnol",
    )
    db.commit()
    await admin_service.update_level(
        AsyncBridge(db), 3, LevelUpdate(lv2_enabled=False), updated_by=ACTEUR,
    )
    db.refresh(enrollment)
    assert enrollment.lv2 == "espagnol"
