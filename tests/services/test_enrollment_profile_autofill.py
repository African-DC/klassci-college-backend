"""Une réinscription reprend la fiche de l'an passé ; un nouvel élève part de rien.

Les tests passent par les vraies portes de création (`create_enrollment`,
`re_enroll_student`, `create_enrollment_with_student`) sur une base SQLite.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessValidationError
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentWithStudentCreate,
    ReEnrollmentCreate,
)
from app.services import enrollment_service
from app.services.enrollment_arrears import ArrearsClearance
from tests.services._sheet_world import (
    ACTEUR,
    AN_COURANT,
    AN_PASSE,
    CLASSE_3E,
    CLASSE_4E,
    CLASSE_6E,
    CLASSE_TLE_D,
    AsyncBridge,
    add_enrollment,
    add_student,
    build_school,
)

ELEVE = 500


@pytest.fixture()
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    async def _silence(*_a: object, **_k: object) -> None:
        return None

    monkeypatch.setattr(
        enrollment_service.enrollment_notifications, "prevenir_qu_il_faut_encaisser", _silence
    )
    yield from build_school()


def _reinscrit_en_4e_l_an_passe(db: Session, **kw: object) -> None:
    add_student(db, ELEVE, "Koné", "Awa")
    add_enrollment(db, 1, ELEVE, CLASSE_4E, AN_PASSE, lv2="espagnol", **kw)
    db.commit()


async def _inscrire(db: Session, class_id: int, **profil: object) -> Enrollment:
    reponse = await enrollment_service.create_enrollment(
        AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentCreate(
            student_id=ELEVE, class_id=class_id, academic_year_id=AN_COURANT, **profil
        ),
        created_by=ACTEUR,
        arrears=ArrearsClearance.INFORM_ONLY,
    )
    inscription = db.get(Enrollment, reponse.id)
    assert inscription is not None
    return inscription


@pytest.mark.asyncio
async def test_passage_au_niveau_suivant_non_redoublant_lv2_reprise(db: Session) -> None:
    _reinscrit_en_4e_l_an_passe(db, artistic_discipline="musique")

    inscription = await _inscrire(db, CLASSE_3E)

    assert inscription.previous_level == "4E"
    assert inscription.is_repeater is False
    assert inscription.lv2 == "espagnol"
    assert inscription.artistic_discipline == "musique"
    assert inscription.previous_series is None


@pytest.mark.asyncio
async def test_meme_niveau_que_l_an_passe_redoublant(db: Session) -> None:
    _reinscrit_en_4e_l_an_passe(db)

    inscription = await _inscrire(db, CLASSE_4E)

    assert inscription.is_repeater is True
    assert inscription.previous_level == "4E"


@pytest.mark.asyncio
async def test_ce_que_le_guichet_tape_l_emporte_sur_l_an_passe(db: Session) -> None:
    _reinscrit_en_4e_l_an_passe(db)

    inscription = await _inscrire(db, CLASSE_3E, lv2="allemand", is_repeater=True)

    assert inscription.lv2 == "allemand"
    assert inscription.is_repeater is True
    assert inscription.previous_level == "4E"


@pytest.mark.asyncio
async def test_une_inscription_annulee_l_an_passe_ne_compte_pas(db: Session) -> None:
    _reinscrit_en_4e_l_an_passe(db, status=EnrollmentStatus.ANNULE)

    inscription = await _inscrire(db, CLASSE_3E)

    assert inscription.previous_level is None
    assert inscription.is_repeater is None
    assert inscription.lv2 is None


@pytest.mark.asyncio
async def test_la_serie_de_l_an_passe_est_reprise(db: Session) -> None:
    add_student(db, ELEVE, "Yao", "Kouassi")
    add_enrollment(db, 1, ELEVE, CLASSE_TLE_D, AN_PASSE)
    db.commit()

    inscription = await _inscrire(db, CLASSE_TLE_D)

    assert inscription.previous_level == "TLE"
    assert inscription.previous_series == "D"
    assert inscription.is_repeater is True


@pytest.mark.asyncio
async def test_un_eleve_sans_antecedent_reste_vide(db: Session) -> None:
    add_student(db, ELEVE, "Traoré", "Aminata")
    db.commit()

    inscription = await _inscrire(db, CLASSE_6E)

    assert inscription.previous_level is None
    assert inscription.previous_series is None
    assert inscription.is_repeater is None
    assert inscription.lv2 is None
    assert inscription.artistic_discipline is None


@pytest.mark.asyncio
async def test_la_reinscription_transmet_la_fiche_tapee(db: Session) -> None:
    add_student(db, ELEVE, "Traoré", "Aminata")
    db.commit()

    reponse = await enrollment_service.re_enroll_student(
        AsyncBridge(db),  # type: ignore[arg-type]
        ReEnrollmentCreate(
            student_id=ELEVE, class_id=CLASSE_6E, academic_year_id=AN_COURANT, previous_level="CM2"
        ),
        created_by=ACTEUR,
        arrears=ArrearsClearance.INFORM_ONLY,
    )

    assert reponse.previous_level == "CM2"


@pytest.mark.asyncio
async def test_une_lv2_en_6e_est_refusee_et_rien_n_est_cree(db: Session) -> None:
    add_student(db, ELEVE, "Traoré", "Aminata")
    db.commit()

    with pytest.raises(BusinessValidationError) as refus:
        await _inscrire(db, CLASSE_6E, lv2="allemand")

    assert refus.value.status_code == 422
    assert "6ème" in refus.value.detail
    assert db.query(Enrollment).filter_by(student_id=ELEVE).count() == 0


@pytest.mark.asyncio
async def test_le_formulaire_nouvel_eleve_garde_ce_qui_est_tape(db: Session) -> None:
    reponse = await enrollment_service.create_enrollment_with_student(
        AsyncBridge(db),  # type: ignore[arg-type]
        EnrollmentWithStudentCreate(
            first_name="Aya",
            last_name="Koffi",
            class_id=CLASSE_4E,
            academic_year_id=AN_COURANT,
            enrollment_number="26000009Z",
            nationality="Ivoirienne",
            previous_level="5E",
            lv2="allemand",
        ),
        created_by=ACTEUR,
        arrears=ArrearsClearance.INFORM_ONLY,
    )

    assert reponse.previous_level == "5E"
    assert reponse.lv2 == "allemand"
    assert reponse.is_repeater is None
    inscription = db.get(Enrollment, reponse.id)
    assert inscription is not None
    assert inscription.student.nationality == "Ivoirienne"
