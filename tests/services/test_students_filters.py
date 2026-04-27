"""Tests pour la résolution `current_enrollment` + endpoint filters de /admin/students.

L'objectif : vérifier que `_student_to_response` attache correctement l'inscription
année courante (et seulement elle), et que `get_students_filters` retourne des
counts cohérents indépendamment des données chargées en mémoire.

Convention de la session : les tests routers chargent app.main → weasyprint →
casse côté Windows (libs GTK manquantes). Donc on teste la logique côté service
avec des objects ORM mockés en SimpleNamespace, ce qui garde la suite portable.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessValidationError
from app.services.admin_service import (
    _student_to_response,
    get_students_filters,
    list_students,
)


def _make_enrollment(
    *,
    enrollment_id: int = 100,
    class_id: int = 1,
    class_name: str = "6ème A",
    status: str = "valide",
) -> SimpleNamespace:
    """Stand-in pour Enrollment ORM — on attache .class_ avec son name."""
    return SimpleNamespace(
        id=enrollment_id,
        class_id=class_id,
        class_=SimpleNamespace(name=class_name),
        status=status,
    )


def _make_student(*, student_id: int = 1, enrollments: list | None = None) -> SimpleNamespace:
    """Stand-in pour Student ORM. enrollments = liste filtrée par with_loader_criteria
    (donc ici simulant le résultat post-filtre)."""
    from datetime import datetime

    now = datetime(2026, 1, 1)
    return SimpleNamespace(
        id=student_id,
        first_name="Awa",
        last_name="Traoré",
        birth_date=None,
        genre="F",
        enrollment_number=f"STU-{student_id:04d}",
        photo_url=None,
        city=None,
        commune=None,
        user_id=student_id + 100,
        created_at=now,
        updated_at=now,
        enrollments=enrollments or [],
    )


# ---------------------------------------------------------------------------
# _student_to_response — attache current_enrollment depuis enrollments filtré
# ---------------------------------------------------------------------------


def test_student_response_with_current_valide_enrollment() -> None:
    """Un élève avec une inscription valide année courante → current_enrollment populée."""
    enrollment = _make_enrollment(enrollment_id=42, class_id=5, class_name="6ème A")
    student = _make_student(enrollments=[enrollment])

    response = _student_to_response(student)

    assert response.current_enrollment is not None
    assert response.current_enrollment.enrollment_id == 42
    assert response.current_enrollment.class_id == 5
    assert response.current_enrollment.class_name == "6ème A"
    assert response.current_enrollment.status == "valide"


def test_student_response_without_enrollment_returns_null() -> None:
    """Un élève sans inscription valide année courante → current_enrollment = null.

    `with_loader_criteria` côté repo a déjà filtré, donc enrollments = []
    signifie 'pas d'inscription valide cette année'.
    """
    student = _make_student(enrollments=[])

    response = _student_to_response(student)

    assert response.current_enrollment is None


def test_student_response_handles_class_relationship_unloaded() -> None:
    """Si .class_ n'est pas chargé (cas dégénéré), class_name fallback à \"\"."""
    enrollment = SimpleNamespace(id=42, class_id=5, class_=None, status="valide")
    student = _make_student(enrollments=[enrollment])

    response = _student_to_response(student)

    assert response.current_enrollment is not None
    assert response.current_enrollment.class_name == ""


# ---------------------------------------------------------------------------
# list_students — mutual exclusivity class_id / unenrolled_only
# ---------------------------------------------------------------------------


async def test_list_students_rejects_class_id_and_unenrolled_combo() -> None:
    """Filtres mutuellement exclusifs : 422 si les deux sont passés."""
    db = AsyncMock()
    with pytest.raises(BusinessValidationError) as exc_info:
        await list_students(db, class_id=5, unenrolled_only=True)
    assert "class_id" in exc_info.value.detail or "unenrolled_only" in exc_info.value.detail
    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# get_students_filters — counts cohérents
# ---------------------------------------------------------------------------


async def test_filters_no_current_year_marks_everyone_unenrolled() -> None:
    """Si aucune année n'est marquée courante, tous les élèves sont 'non inscrits'."""
    from app.repositories import admin_repository

    # Mock le repository pour retourner le payload "pas d'année courante"
    async def fake_get_filters(db):
        return {
            "total": 10,
            "by_class": [],
            "no_current_enrollment_count": 10,
            "current_academic_year_id": None,
        }

    original = admin_repository.get_students_filters
    admin_repository.get_students_filters = fake_get_filters
    try:
        result = await get_students_filters(AsyncMock())
    finally:
        admin_repository.get_students_filters = original

    assert result.total == 10
    assert result.no_current_enrollment_count == 10
    assert result.by_class == []
    assert result.current_academic_year_id is None


async def test_filters_returns_counts_per_class() -> None:
    """Counts par classe + sans-inscription pour année courante."""
    from app.repositories import admin_repository

    async def fake_get_filters(db):
        return {
            "total": 50,
            "by_class": [
                {"class_id": 1, "class_name": "6ème A", "count": 12},
                {"class_id": 2, "class_name": "1ère C", "count": 8},
            ],
            "no_current_enrollment_count": 3,
            "current_academic_year_id": 7,
        }

    original = admin_repository.get_students_filters
    admin_repository.get_students_filters = fake_get_filters
    try:
        result = await get_students_filters(AsyncMock())
    finally:
        admin_repository.get_students_filters = original

    assert result.total == 50
    assert result.no_current_enrollment_count == 3
    assert len(result.by_class) == 2
    assert result.by_class[0].class_name == "6ème A"
    assert result.by_class[0].count == 12
    assert result.current_academic_year_id == 7
    # Sanity check : 12 + 8 + 3 = 23, donc 27 élèves sont en non-valide ou multi-tenant
    # (le total est indépendant des cohortes — un élève peut n'être nulle part).


# ---------------------------------------------------------------------------
# get_student_by_id — eager-load obligatoire (regression PR #83 → hotfix)
# ---------------------------------------------------------------------------


async def test_get_student_by_id_eager_loads_enrollments() -> None:
    """Régression : sans selectinload, _student_to_response déclenche MissingGreenlet en prod.

    PR #83 a ajouté la lecture de `s.enrollments` dans `_student_to_response`,
    mais `repo.get_student_by_id` n'avait pas été mis à jour pour eager-loader
    cette relation. Résultat : 4 endpoints cassés en cascade (GET / POST / PATCH /
    photo upload) — l'admin en prod voyait "Connexion au serveur impossible".

    Ce test garantit que la fonction emit bien un select(Student) AVEC loader
    options. On l'inspecte via _with_options (interne SQLAlchemy 2.0 mais stable).
    """
    from app.repositories.admin_repository import get_student_by_id

    captured: dict = {"stmts": []}

    async def fake_execute(stmt: object) -> MagicMock:
        captured["stmts"].append(stmt)
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        result.scalar = MagicMock(return_value=None)
        return result

    db = AsyncMock()
    db.execute = fake_execute

    await get_student_by_id(db, 1)

    # 2 executes attendus : (1) get_current_academic_year_id, (2) le select Student
    stmts = captured["stmts"]
    assert len(stmts) == 2, f"Expected 2 db.execute calls (year + student), got {len(stmts)}"

    student_stmt = stmts[1]
    options = getattr(student_stmt, "_with_options", ())
    assert options, (
        "get_student_by_id doit appliquer selectinload sur Student.enrollments — "
        "sans, _student_to_response trigger MissingGreenlet en prod async session"
    )
