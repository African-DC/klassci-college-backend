"""Le lieu de naissance de l'élève, de la saisie jusqu'aux pièces officielles.

Ces tests appellent les fonctions et vérifient ce qu'elles produisent. Aucun
n'inspecte le code source : un test qui lit le source fige le bug qu'il
observe au lieu de le révéler, et c'est précisément ainsi qu'un certificat
faux a pu survivre à sa propre couverture.

Le faux en question : le certificat de scolarité imprimait la **ville de
résidence** à la place du lieu de naissance, faute de champ dédié. Un élève né
à Bouaké et domicilié à Cocody se voyait déclaré « né à Cocody » sur un
document opposable à l'administration.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.user import Student
from app.schemas.admin import StudentCreate, StudentResponse, StudentUpdate
from app.schemas.enrollment import EnrollmentWithStudentCreate
from app.services.pdf._helpers import OFFICIAL_BLANK, birth_mention

# ---------------------------------------------------------------------------
# La mention d'état civil — source unique des deux certificats
# ---------------------------------------------------------------------------


def test_birth_mention_prints_the_place_that_was_entered() -> None:
    """Le lieu saisi ressort tel quel, sans reformulation."""
    date_str, place = birth_mention({"birth_date": date(2010, 5, 15), "birth_place": "Bouaké"})

    assert date_str == "15/05/2010"
    assert place == "Bouaké"


def test_birth_mention_never_falls_back_to_the_residence_city() -> None:
    """Le domicile ne doit JAMAIS tenir lieu de lieu de naissance.

    C'est la régression qui produisait un certificat faux : `city` renseignée,
    lieu de naissance inconnu, et le document affirmait quand même « né à ».
    """
    student = {
        "birth_date": date(2010, 5, 15),
        "birth_place": None,
        "city": "Abidjan",
        "commune": "Cocody",
    }

    _, place = birth_mention(student)

    assert "Abidjan" not in place
    assert "Cocody" not in place
    assert place == OFFICIAL_BLANK


def test_birth_mention_blanks_are_never_none_nor_empty() -> None:
    """Sans date ni lieu, on imprime des points de suite — pas « None », pas un trou."""
    date_str, place = birth_mention({})

    assert date_str == OFFICIAL_BLANK
    assert place == OFFICIAL_BLANK
    for value in (date_str, place):
        assert "None" not in value
        assert value.strip()


def test_birth_mention_treats_whitespace_as_missing() -> None:
    """Un lieu réduit à des espaces vaut absent, pas une mention vide."""
    _, place = birth_mention({"birth_place": "   "})

    assert place == OFFICIAL_BLANK


# ---------------------------------------------------------------------------
# Certificat de scolarité — la mention doit apparaître dans le corps
# ---------------------------------------------------------------------------


def _certificate_body(student: dict) -> str:
    """Corps HTML du certificat pour un élève donné."""
    from app.services.pdf.certificate_scolarite import _body_paragraph

    date_str, place = birth_mention(student)
    return _body_paragraph(
        signatory_html="Le Chef d'Établissement",
        full_name="Aya Koffi",
        ne_form="née",
        birth_date_str=date_str,
        birthplace=place,
        matricule="2024-001",
        inscrit_form="inscrite",
        class_name="6e A",
        academic_year_name="2025-2026",
    )


def test_certificate_body_carries_the_birth_place() -> None:
    """« née le 15/05/2010 à Bouaké » doit figurer sur le certificat."""
    body = _certificate_body({"birth_date": date(2010, 5, 15), "birth_place": "Bouaké"})

    assert "Bouaké" in body
    assert "15/05/2010" in body
    assert "née le" in body


def test_certificate_body_survives_a_missing_birth_place() -> None:
    """Lieu inconnu : le certificat sort quand même, sans « None » ni trou."""
    body = _certificate_body({"birth_date": date(2010, 5, 15), "birth_place": None})

    assert "None" not in body
    assert OFFICIAL_BLANK in body
    # La mention reste présente : la retirer rendrait la pièce non conforme.
    assert "née le" in body


def test_certificate_body_does_not_pass_off_the_city_as_a_birth_place() -> None:
    body = _certificate_body(
        {"birth_date": date(2010, 5, 15), "birth_place": None, "city": "Abidjan"}
    )

    assert "Abidjan" not in body


# ---------------------------------------------------------------------------
# Attestation de fréquentation — même exigence de conformité
# ---------------------------------------------------------------------------


def _attendance_body(student: dict) -> str:
    from app.services.pdf.attendance_certificate import _body_paragraph

    date_str, place = birth_mention(student)
    return _body_paragraph(
        signatory_html="Le Chef d'Établissement",
        full_name="Aya Koffi",
        ne_form="née",
        birth_date_str=date_str,
        birthplace=place,
        matricule="2024-001",
        inscrit_form="inscrite",
        class_name="6e A",
        academic_year_name="2025-2026",
        issued_str="21/08/2026",
        rate=94.5,
        total=120,
    )


def test_attendance_certificate_carries_the_birth_mention() -> None:
    """L'attestation identifie l'élève par « né(e) le ... à ... »."""
    body = _attendance_body({"birth_date": date(2010, 5, 15), "birth_place": "Korhogo"})

    assert "Korhogo" in body
    assert "15/05/2010" in body


def test_attendance_certificate_survives_a_missing_birth_place() -> None:
    body = _attendance_body({"birth_date": None, "birth_place": None})

    assert "None" not in body
    assert "94.50%" in body


# ---------------------------------------------------------------------------
# Fiche d'inscription — la ligne « À » de la grille identité
# ---------------------------------------------------------------------------


def test_enrollment_form_identity_block_shows_the_birth_place() -> None:
    from app.services.pdf._enrollment_form_parts import student_identity_block

    html = student_identity_block(
        {
            "first_name": "Aya",
            "last_name": "Koffi",
            "genre": "F",
            "birth_date": date(2010, 5, 15),
            "birth_place": "Man",
            "city": "Abidjan",
            "commune": "Cocody",
        }
    )

    assert "Man" in html
    assert "Né(e) le" in html


def test_enrollment_form_identity_block_survives_a_missing_birth_place() -> None:
    """Sans lieu, la grille affiche son tiret habituel — jamais « None »."""
    from app.services.pdf._enrollment_form_parts import student_identity_block

    html = student_identity_block(
        {
            "first_name": "Aya",
            "last_name": "Koffi",
            "genre": "F",
            "birth_date": date(2010, 5, 15),
            "birth_place": None,
            "city": "Abidjan",
        }
    )

    assert "None" not in html
    # La ville de résidence ne doit pas remonter dans la ligne « À ».
    assert html.count("Abidjan") == 1  # uniquement la ligne « Ville · Commune »


# ---------------------------------------------------------------------------
# Aller-retour création : ce qui est saisi doit être relu tel quel
# ---------------------------------------------------------------------------


def test_created_birth_place_is_read_back_unchanged() -> None:
    """Chaîne réelle de la création : schéma → dump → ORM → réponse API.

    Si une seule couche laisse tomber le champ, la valeur relue diverge.
    """
    payload = StudentCreate(
        first_name="Aya",
        last_name="Koffi",
        email="aya@example.ci",
        password="Passw0rd!",
        birth_date=date(2010, 5, 15),
        birth_place="Bouaké",
        genre="F",
    )

    # admin_service.create_student : dump puis Student(**profile_data).
    profile_data = payload.model_dump(exclude={"email", "password"})
    assert profile_data["birth_place"] == "Bouaké"

    student = Student(**profile_data, user_id=7)
    now = datetime.now(UTC)
    student.id, student.created_at, student.updated_at = 1, now, now
    student.photo_url = None
    student.enrollments = []

    response = StudentResponse.model_validate(student)

    assert response.birth_place == "Bouaké"


def test_enrollment_with_student_create_carries_the_birth_place() -> None:
    """Le parcours d'inscription crée l'élève : le lieu doit y transiter."""
    payload = EnrollmentWithStudentCreate(
        first_name="Aya",
        last_name="Koffi",
        birth_date=date(2010, 5, 15),
        birth_place="Man",
        class_id=3,
    )

    assert payload.birth_place == "Man"


# ---------------------------------------------------------------------------
# Aller-retour modification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_updated_birth_place_is_read_back_modified() -> None:
    """Modifié, le lieu doit être relu modifié — pas l'ancienne valeur."""
    from app.repositories import admin_repository as repo

    student = Student(first_name="Aya", last_name="Koffi", birth_place="Bouaké")
    now = datetime.now(UTC)
    student.id, student.user_id, student.created_at, student.updated_at = 1, None, now, now
    student.photo_url = None
    student.enrollments = []

    changes = StudentUpdate(birth_place="Korhogo").model_dump(exclude_none=True, mode="json")
    assert changes == {"birth_place": "Korhogo"}

    await repo.update_student(AsyncMock(), student, **changes)

    assert StudentResponse.model_validate(student).birth_place == "Korhogo"


# ---------------------------------------------------------------------------
# Le constructeur de réponse de la fiche détail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_student_full_projection_includes_the_birth_place() -> None:
    """`get_student_full` compose son dict à la main : tout champ omis ici est
    enregistré puis jamais relu, sans que rien ne le signale."""
    from app.services import admin_service
    from app.services.admin_service import FinanceView

    now = datetime.now(UTC)
    student = SimpleNamespace(
        id=1,
        first_name="Aya",
        last_name="Koffi",
        birth_date=date(2010, 5, 15),
        birth_place="Bouaké",
        genre="F",
        enrollment_number="2024-001",
        photo_url=None,
        user_id=None,
        user=None,
        created_at=now,
        updated_at=now,
    )

    student_result = MagicMock()
    student_result.scalar_one_or_none.return_value = student
    enrollment_result = MagicMock()
    enrollment_result.scalar_one_or_none.return_value = None
    attendance_result = MagicMock()
    attendance_result.one_or_none.return_value = None

    db = AsyncMock()
    db.execute.side_effect = [student_result, enrollment_result, attendance_result]

    with (
        patch.object(
            admin_service, "_mandatory_expected_and_paid", new=AsyncMock(return_value=(0.0, 0.0))
        ),
        patch.object(admin_service, "_student_trimester_grades", new=AsyncMock(return_value=[])),
        patch.object(admin_service, "_student_trimester_absences", new=AsyncMock(return_value=[])),
    ):
        result = await admin_service.get_student_full(
            db, 1, finance=FinanceView.of(may_read_payments=True, may_read_status=False)
        )

    assert result["birth_place"] == "Bouaké"


# ---------------------------------------------------------------------------
# Import CSV
# ---------------------------------------------------------------------------


def test_csv_row_parses_the_birth_place_column() -> None:
    from app.services.csv_import_service import _validate_row

    data, error = _validate_row(
        {
            "first_name": "Aya",
            "last_name": "Koffi",
            "birth_date": "2010-05-15",
            "birth_place": "Bouaké",
            "genre": "F",
            "enrollment_number": "",
            "class_name": "6eme A",
        },
        2,
    )

    assert error is None
    assert data is not None
    assert data["birth_place"] == "Bouaké"


def test_csv_without_the_birth_place_column_still_imports() -> None:
    """La colonne est facultative : un fichier d'école déjà constitué passe."""
    from app.services.csv_import_service import _validate_row

    data, error = _validate_row(
        {
            "first_name": "Aya",
            "last_name": "Koffi",
            "birth_date": "2010-05-15",
            "genre": "F",
            "enrollment_number": "",
            "class_name": "6eme A",
        },
        2,
    )

    assert error is None
    assert data is not None
    assert data["birth_place"] is None
