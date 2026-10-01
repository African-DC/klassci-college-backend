"""Corriger la fiche (une inscription, un lot) et poser ou retirer une bourse."""

from collections.abc import Iterator
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.core.audit import AuditLog
from app.core.exceptions import BusinessValidationError, ConflictError
from app.models.deep_report import Scholarship
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.schemas.enrollment import EnrollmentUpdate
from app.schemas.enrollment_profile import (
    EnrollmentProfileBatchRequest,
    EnrollmentProfileUpdate,
    ScholarshipUpsert,
)
from app.services import enrollment_profile_update, enrollment_scholarship, enrollment_service
from tests.services._sheet_world import (
    ACTEUR,
    AN_COURANT,
    CLASSE_3E,
    CLASSE_4E,
    CLASSE_6E,
    AsyncBridge,
    add_enrollment,
    add_student,
    build_school,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    for session in build_school():
        for i in (1, 2, 3):
            add_student(session, i, f"Nom{i}", f"Prenom{i}")
        add_enrollment(session, 1, 1, CLASSE_4E, AN_COURANT, previous_series="C", is_repeater=False)
        add_enrollment(session, 2, 2, CLASSE_4E, AN_COURANT)
        add_enrollment(session, 3, 3, CLASSE_6E, AN_COURANT)
        session.commit()
        yield session


def _bridge(db: Session) -> AsyncBridge:
    return AsyncBridge(db)


@pytest.mark.asyncio
async def test_un_champ_absent_reste_un_null_envoye_efface(db: Session) -> None:
    reponse = await enrollment_profile_update.update_profile(
        _bridge(db),  # type: ignore[arg-type]
        1,
        EnrollmentProfileUpdate.model_validate({"previous_series": None, "lv2": "espagnol"}),
        updated_by=ACTEUR,
    )

    assert reponse.previous_series is None
    assert reponse.lv2 == "espagnol"
    assert reponse.is_repeater is False
    journal = db.query(AuditLog).filter_by(entity_type="enrollment", entity_id=1).one()
    assert journal.new_values == {"previous_series": None, "lv2": "espagnol"}
    assert journal.old_values == {"previous_series": "C", "lv2": None}


@pytest.mark.asyncio
async def test_une_lv2_sur_une_6e_est_refusee(db: Session) -> None:
    with pytest.raises(BusinessValidationError):
        await enrollment_profile_update.update_profile(
            _bridge(db),  # type: ignore[arg-type]
            3,
            EnrollmentProfileUpdate(lv2="allemand"),
            updated_by=ACTEUR,
        )
    assert db.get(Enrollment, 3).lv2 is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_le_lot_passe_en_entier(db: Session) -> None:
    resultat = await enrollment_profile_update.update_profiles_in_batch(
        _bridge(db),  # type: ignore[arg-type]
        EnrollmentProfileBatchRequest.model_validate(
            {
                "items": [
                    {"enrollment_id": 1, "lv2": "allemand"},
                    {"enrollment_id": 2, "is_repeater": True},
                    {"enrollment_id": 3, "artistic_discipline": "musique"},
                ]
            }
        ),
        updated_by=ACTEUR,
    )

    assert resultat == {"updated": 3}
    db.expire_all()
    assert db.get(Enrollment, 1).lv2 == "allemand"  # type: ignore[union-attr]
    assert db.get(Enrollment, 2).is_repeater is True  # type: ignore[union-attr]
    assert db.get(Enrollment, 3).artistic_discipline == "musique"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_le_lot_refuse_ne_modifie_rien_et_nomme_la_fautive(db: Session) -> None:
    with pytest.raises(BusinessValidationError) as refus:
        await enrollment_profile_update.update_profiles_in_batch(
            _bridge(db),  # type: ignore[arg-type]
            EnrollmentProfileBatchRequest.model_validate(
                {
                    "items": [
                        {"enrollment_id": 1, "lv2": "allemand"},
                        {"enrollment_id": 3, "lv2": "espagnol"},
                    ]
                }
            ),
            updated_by=ACTEUR,
        )

    assert "[3]" in refus.value.detail
    db.expire_all()
    assert db.get(Enrollment, 1).lv2 is None  # type: ignore[union-attr]
    assert db.query(AuditLog).count() == 0


@pytest.mark.asyncio
async def test_le_lot_avec_une_inscription_inconnue_est_refuse(db: Session) -> None:
    with pytest.raises(BusinessValidationError) as refus:
        await enrollment_profile_update.update_profiles_in_batch(
            _bridge(db),  # type: ignore[arg-type]
            EnrollmentProfileBatchRequest.model_validate(
                {"items": [{"enrollment_id": 1, "is_repeater": True}, {"enrollment_id": 999}]}
            ),
            updated_by=ACTEUR,
        )

    assert "[999]" in refus.value.detail
    db.expire_all()
    assert db.get(Enrollment, 1).is_repeater is False  # type: ignore[union-attr]


def test_un_lot_de_plus_de_cent_est_refuse_par_le_schema() -> None:
    with pytest.raises(ValueError):
        EnrollmentProfileBatchRequest.model_validate(
            {"items": [{"enrollment_id": i} for i in range(1, 102)]}
        )


@pytest.mark.asyncio
async def test_la_bourse_se_pose_se_remplace_et_se_retire(db: Session) -> None:
    bridge = _bridge(db)
    await enrollment_scholarship.upsert_scholarship(
        bridge,  # type: ignore[arg-type]
        2,
        ScholarshipUpsert(kind="demi_bourse", provider="Etat"),
        actor=ACTEUR,
    )
    remplacee = await enrollment_scholarship.upsert_scholarship(
        bridge,  # type: ignore[arg-type]
        2,
        ScholarshipUpsert(kind="bourse_entiere", decision_number="D-12"),
        actor=ACTEUR,
    )

    assert remplacee.kind == "bourse_entiere"
    bourses = db.query(Scholarship).filter_by(enrollment_id=2).all()
    assert len(bourses) == 1
    assert bourses[0].provider is None
    vue = await enrollment_service.get_enrollment(bridge, 2)  # type: ignore[arg-type]
    assert vue.scholarship is not None
    assert vue.scholarship.decision_number == "D-12"

    await enrollment_scholarship.delete_scholarship(bridge, 2, actor=ACTEUR)  # type: ignore[arg-type]

    assert db.query(Scholarship).filter_by(enrollment_id=2).count() == 0
    db.expire_all()
    vue = await enrollment_service.get_enrollment(bridge, 2)  # type: ignore[arg-type]
    assert vue.scholarship is None
    assert db.query(AuditLog).filter_by(entity_id=2).count() == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fermeture",
    [
        {"status": EnrollmentStatus.ANNULE},
        {"status": EnrollmentStatus.REJETE},
        {"archived_at": datetime(2026, 9, 9)},
    ],
)
async def test_pas_de_bourse_sur_un_dossier_ferme(
    db: Session, fermeture: dict[str, object]
) -> None:
    inscription = db.get(Enrollment, 2)
    assert inscription is not None
    for champ, valeur in fermeture.items():
        setattr(inscription, champ, valeur)
    db.commit()

    with pytest.raises(BusinessValidationError) as refus:
        await enrollment_scholarship.upsert_scholarship(
            _bridge(db),  # type: ignore[arg-type]
            2,
            ScholarshipUpsert(kind="demi_bourse"),
            actor=ACTEUR,
        )

    assert refus.value.status_code == 422
    assert "bourse" in refus.value.detail
    assert db.query(Scholarship).count() == 0


@pytest.mark.asyncio
async def test_une_bourse_posee_entre_lecture_et_ecriture_est_remplacee(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le second guichet bute sur l'index unique, relit, et remplace."""
    db.add(Scholarship(enrollment_id=2, kind="demi_bourse", provider="Premier guichet"))
    db.commit()
    lecture_reelle = enrollment_scholarship._current
    lectures: list[int] = []

    async def lecture_en_retard(session: object, enrollment_id: int) -> object:
        lectures.append(enrollment_id)
        if len(lectures) == 1:
            return None  # n'a pas encore vu la bourse de l'autre guichet
        return await lecture_reelle(session, enrollment_id)  # type: ignore[arg-type]

    monkeypatch.setattr(enrollment_scholarship, "_current", lecture_en_retard)

    await enrollment_scholarship.upsert_scholarship(
        _bridge(db),  # type: ignore[arg-type]
        2,
        ScholarshipUpsert(kind="bourse_entiere"),
        actor=ACTEUR,
    )

    assert len(lectures) == 2
    bourses = db.query(Scholarship).filter_by(enrollment_id=2).all()
    assert [(b.kind, b.provider) for b in bourses] == [("bourse_entiere", None)]


@pytest.mark.asyncio
async def test_deux_conflits_de_suite_rendent_un_409(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.add(Scholarship(enrollment_id=2, kind="demi_bourse"))
    db.commit()

    async def ne_voit_jamais_rien(*_a: object) -> None:
        return None

    monkeypatch.setattr(enrollment_scholarship, "_current", ne_voit_jamais_rien)

    with pytest.raises(ConflictError) as refus:
        await enrollment_scholarship.upsert_scholarship(
            _bridge(db),  # type: ignore[arg-type]
            2,
            ScholarshipUpsert(kind="bourse_entiere"),
            actor=ACTEUR,
        )

    assert refus.value.status_code == 409
    assert db.query(Scholarship).filter_by(enrollment_id=2).count() == 1


@pytest.mark.asyncio
async def test_passer_en_6e_retire_la_lv2_et_le_journalise(db: Session) -> None:
    inscription = db.get(Enrollment, 1)
    assert inscription is not None
    inscription.lv2 = "allemand"
    db.commit()

    reponse = await enrollment_service.update_enrollment(
        _bridge(db),  # type: ignore[arg-type]
        1,
        EnrollmentUpdate(class_id=CLASSE_6E),
        updated_by=ACTEUR,
    )

    assert reponse.class_id == CLASSE_6E
    assert reponse.lv2 is None
    retrait = (
        db.query(AuditLog)
        .filter_by(entity_type="enrollment", entity_id=1)
        .filter(AuditLog.notes.is_not(None))
        .one()
    )
    assert retrait.old_values == {"lv2": "allemand"}
    assert retrait.new_values == {"lv2": None}


@pytest.mark.asyncio
async def test_changer_pour_une_classe_qui_l_enseigne_garde_la_lv2(db: Session) -> None:
    inscription = db.get(Enrollment, 2)
    assert inscription is not None
    inscription.lv2 = "espagnol"
    db.commit()

    reponse = await enrollment_service.update_enrollment(
        _bridge(db),  # type: ignore[arg-type]
        2,
        EnrollmentUpdate(class_id=CLASSE_3E),
        updated_by=ACTEUR,
    )

    assert reponse.lv2 == "espagnol"
