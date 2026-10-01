"""Corriger le niveau antérieur recalcule la qualité, comme à la création.

L'inscription 1 est en 4ème (code 4E) et porte « non redoublant ». Corriger
son niveau de l'an passé sans dire la qualité doit la remettre d'accord avec
le niveau ; une qualité envoyée dans le même corps l'emporte.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.models.academic import Class, Level
from app.models.enrollment import Enrollment
from app.schemas.enrollment_profile import EnrollmentProfileBatchRequest, EnrollmentProfileUpdate
from app.services import enrollment_profile_update
from tests.services._sheet_world import (
    ACTEUR,
    AN_COURANT,
    CLASSE_4E,
    CLASSE_6E,
    AsyncBridge,
    add_enrollment,
    add_student,
    build_school,
)

CLASSE_INCONNUE = 90


@pytest.fixture()
def db() -> Iterator[Session]:
    for session in build_school():
        session.add_all(
            [
                Level(id=90, name="Classe passerelle", order=9),
                Class(id=CLASSE_INCONNUE, name="Passerelle 1", level_id=90),
            ]
        )
        for i in (1, 2, 3):
            add_student(session, i, f"Nom{i}", f"Prenom{i}")
        add_enrollment(session, 1, 1, CLASSE_4E, AN_COURANT, is_repeater=False)
        add_enrollment(session, 2, 2, CLASSE_6E, AN_COURANT, previous_level="CM2")
        add_enrollment(session, 3, 3, CLASSE_INCONNUE, AN_COURANT, is_repeater=True)
        session.commit()
        yield session


async def _patch(db: Session, enrollment_id: int, body: dict[str, object]) -> Enrollment:
    await enrollment_profile_update.update_profile(
        AsyncBridge(db),  # type: ignore[arg-type]
        enrollment_id,
        EnrollmentProfileUpdate.model_validate(body),
        updated_by=ACTEUR,
    )
    db.expire_all()
    enrollment = db.get(Enrollment, enrollment_id)
    assert enrollment is not None
    return enrollment


@pytest.mark.asyncio
async def test_meme_niveau_que_la_classe_devient_redoublant_et_se_journalise(
    db: Session,
) -> None:
    enrollment = await _patch(db, 1, {"previous_level": "4E"})

    assert enrollment.is_repeater is True
    journal = db.query(AuditLog).filter_by(entity_type="enrollment", entity_id=1).one()
    assert journal.old_values == {"previous_level": None, "is_repeater": False}
    assert journal.new_values == {"previous_level": "4E", "is_repeater": True}


@pytest.mark.asyncio
async def test_un_autre_niveau_donne_non_redoublant(db: Session) -> None:
    enrollment = await _patch(db, 1, {"previous_level": "5E"})

    assert enrollment.is_repeater is False


@pytest.mark.asyncio
async def test_effacer_le_niveau_efface_la_qualite(db: Session) -> None:
    enrollment = await _patch(db, 1, {"previous_level": None})

    assert enrollment.is_repeater is None


@pytest.mark.asyncio
async def test_une_qualite_envoyee_l_emporte(db: Session) -> None:
    enrollment = await _patch(db, 1, {"previous_level": "4E", "is_repeater": False})

    assert enrollment.is_repeater is False


@pytest.mark.asyncio
async def test_sans_niveau_envoye_la_qualite_ne_bouge_pas(db: Session) -> None:
    enrollment = await _patch(db, 1, {"lv2": "allemand"})

    assert enrollment.is_repeater is False


@pytest.mark.asyncio
async def test_une_classe_au_niveau_inconnu_ne_permet_rien_d_affirmer(db: Session) -> None:
    enrollment = await _patch(db, 3, {"previous_level": "3E"})

    assert enrollment.is_repeater is None


@pytest.mark.asyncio
async def test_le_lot_suit_les_memes_regles(db: Session) -> None:
    await enrollment_profile_update.update_profiles_in_batch(
        AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentProfileBatchRequest.model_validate(
            {
                "items": [
                    {"enrollment_id": 1, "previous_level": "4E"},
                    {"enrollment_id": 2, "previous_level": "6E", "is_repeater": False},
                    {"enrollment_id": 3, "previous_level": None},
                ]
            }
        ),
        updated_by=ACTEUR,
    )

    db.expire_all()
    assert db.get(Enrollment, 1).is_repeater is True  # type: ignore[union-attr]
    assert db.get(Enrollment, 2).is_repeater is False  # type: ignore[union-attr]
    assert db.get(Enrollment, 3).is_repeater is None  # type: ignore[union-attr]
