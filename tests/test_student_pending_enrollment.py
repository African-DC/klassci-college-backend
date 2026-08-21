"""Une inscription engagée n'est pas une absence d'inscription.

L'écran des élèves affichait « À inscrire » à un élève dont le dossier était
déjà ouvert, en classe, avec ses frais calculés — simplement parce que
l'inscription n'était pas encore validée. Le badge renvoyait vers la création
d'une NOUVELLE inscription : le secrétariat était invité à créer un doublon.

On sépare donc les deux : `current_enrollment` reste l'inscription validée,
`pending_enrollment` porte celle qui est engagée et attend sa validation.
"""

from types import SimpleNamespace

import pytest

from app.models.enrollment import EnrollmentStatus
from app.services.admin_service import _student_to_response


def _eleve(*inscriptions: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        first_name="Awa",
        last_name="Traoré",
        birth_date=None,
        genre="F",
        enrollment_number="COL001",
        photo_url=None,
        city=None,
        commune=None,
        user_id=None,
        created_at="2026-08-21T00:00:00",
        updated_at="2026-08-21T00:00:00",
        enrollments=list(inscriptions),
    )


def _inscription(eid: int, statut: EnrollmentStatus) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid,
        class_id=3,
        class_=SimpleNamespace(id=3, name="6ème A"),
        status=statut,
    )


@pytest.mark.parametrize(
    "statut", [EnrollmentStatus.PROSPECT, EnrollmentStatus.EN_VALIDATION]
)
def test_une_inscription_engagee_ressort_comme_en_attente(statut: EnrollmentStatus) -> None:
    reponse = _student_to_response(_eleve(_inscription(7, statut)))

    assert reponse.current_enrollment is None, "elle n'est pas validée"
    assert reponse.pending_enrollment is not None, (
        "sans ce champ, l'écran propose de créer un second dossier"
    )
    assert reponse.pending_enrollment.enrollment_id == 7
    assert reponse.pending_enrollment.class_name == "6ème A"


def test_une_inscription_validee_reste_linscription_courante() -> None:
    reponse = _student_to_response(_eleve(_inscription(7, EnrollmentStatus.VALIDE)))

    assert reponse.current_enrollment is not None
    assert reponse.current_enrollment.enrollment_id == 7
    assert reponse.pending_enrollment is None


def test_la_validee_lemporte_sur_lengagee() -> None:
    """Un élève réinscrit peut porter les deux : c'est la validée qui compte."""
    reponse = _student_to_response(
        _eleve(
            _inscription(7, EnrollmentStatus.PROSPECT),
            _inscription(8, EnrollmentStatus.VALIDE),
        )
    )

    assert reponse.current_enrollment.enrollment_id == 8
    assert reponse.pending_enrollment is None


def test_sans_aucune_inscription_les_deux_champs_sont_vides() -> None:
    reponse = _student_to_response(_eleve())

    assert reponse.current_enrollment is None
    assert reponse.pending_enrollment is None


def test_la_plus_avancee_est_retenue() -> None:
    """« En validation » passe avant « prospect » : c'est celle qu'on suit."""
    reponse = _student_to_response(
        _eleve(
            _inscription(7, EnrollmentStatus.PROSPECT),
            _inscription(8, EnrollmentStatus.EN_VALIDATION),
        )
    )

    assert reponse.pending_enrollment.enrollment_id == 8
