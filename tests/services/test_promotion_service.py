"""Tests pour `promotion_service` — bulk year rollover (cycle 3 plan B).

Pattern : mocks de `enrollment_repository.*` et `enrollment_service.create_enrollment`
avec `SimpleNamespace` ORM stubs. Pas de vraie DB (cf. lesson cycle 1 retro
sur weasyprint Windows). Les tests vérifient :

- Pre-flight refuse mapping vide / AY identiques / classes destination missing
- Preview retourne capacity warnings sans bloquer
- Execute happy path : N students promoted, fees auto-créés (via mock)
- Execute partial : capacity overflow → 1 erreur, autres OK
- Execute idempotent : retry skip déjà-promus

Les tests routeur (`tests/routers/test_promotions.py`) couvriront le contrat HTTP.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessValidationError
from app.models.enrollment import EnrollmentStatus
from app.services import promotion_service


def _make_class(class_id: int, ay_id: int, name: str = "Test", max_students: int = 30):
    return SimpleNamespace(
        id=class_id,
        academic_year_id=ay_id,
        name=name,
        max_students=max_students,
    )


def _make_enrollment(
    enrollment_id: int,
    student_id: int,
    class_id: int,
    ay_id: int,
    status: EnrollmentStatus = EnrollmentStatus.VALIDE,
):
    return SimpleNamespace(
        id=enrollment_id,
        student_id=student_id,
        class_id=class_id,
        academic_year_id=ay_id,
        status=status,
    )


# ---------------------------------------------------------------------------
# Pre-flight (_validate_run_inputs via preview/execute)
# ---------------------------------------------------------------------------


async def test_preview_rejects_empty_mapping() -> None:
    db = AsyncMock()
    with pytest.raises(BusinessValidationError) as exc:
        await promotion_service.preview_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={}
        )
    assert "mapping" in exc.value.detail.lower()


async def test_preview_rejects_same_source_target() -> None:
    db = AsyncMock()
    with pytest.raises(BusinessValidationError) as exc:
        await promotion_service.preview_promotion(
            db, source_ay_id=1, target_ay_id=1, class_mapping={10: 20}
        )
    assert "différentes" in exc.value.detail


async def test_preview_rejects_missing_target_classes() -> None:
    """Aucune classe trouvée pour les target ids → 422 avec liste explicite."""
    db = AsyncMock()
    # Mock db.execute pour le SELECT classes : retourne 0 row
    classes_result = MagicMock()
    classes_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=classes_result)

    with pytest.raises(BusinessValidationError) as exc:
        await promotion_service.preview_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={10: 20, 11: 21}
        )
    assert "introuvables" in exc.value.detail
    assert "20" in exc.value.detail or "21" in exc.value.detail


# ---------------------------------------------------------------------------
# Preview happy path + capacity warnings
# ---------------------------------------------------------------------------


async def test_preview_returns_summaries_and_warnings() -> None:
    """Preview retourne summary par source class + warnings si overflow."""
    target_class_a = _make_class(20, ay_id=2, name="5ème A", max_students=30)
    target_class_b = _make_class(21, ay_id=2, name="5ème B", max_students=10)

    # Source class 10 → target 20 (cap 30, ok)
    # Source class 11 → target 21 (cap 10, mais 15 students = overflow 5)
    db = AsyncMock()

    # 1st execute : SELECT classes (pre-flight) — retourne les 2 target classes
    # 2nd execute : SELECT enrollment.class_id (count source) — retourne 12 + 15 rows
    # 3rd, 4th execute : count_active_enrollments_for_class (existing in target) — 0 + 0
    classes_result = MagicMock()
    classes_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[target_class_a, target_class_b]))
    )
    source_rows = [(10,)] * 12 + [(11,)] * 15
    source_result = MagicMock()
    source_result.all = MagicMock(return_value=source_rows)

    db.execute = AsyncMock(side_effect=[classes_result, source_result])

    # Patch repo helper
    from app.repositories import enrollment_repository

    original_count = enrollment_repository.count_active_enrollments_for_class
    enrollment_repository.count_active_enrollments_for_class = AsyncMock(return_value=0)
    try:
        result = await promotion_service.preview_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={10: 20, 11: 21}
        )
    finally:
        enrollment_repository.count_active_enrollments_for_class = original_count

    assert result.source_ay_id == 1
    assert result.target_ay_id == 2
    assert result.promotable_count == 27  # 12 + 15
    assert len(result.source_classes) == 2

    # Capacity warning sur la classe B (15 demandé, 10 dispo, overflow 5)
    assert len(result.capacity_warnings) == 1
    warning = result.capacity_warnings[0]
    assert warning.target_class_id == 21
    assert warning.requested == 15
    assert warning.available == 10
    assert warning.overflow == 5


# ---------------------------------------------------------------------------
# Execute happy path + idempotency + partial fail
# ---------------------------------------------------------------------------


async def test_execute_happy_path_promotes_all() -> None:
    """3 students valides → 3 nouveaux enrollments, 0 skipped, 0 errors."""
    target_class = _make_class(20, ay_id=2, name="5ème A", max_students=30)

    classes_result = MagicMock()
    classes_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[target_class]))
    )

    source_enrollments = [
        _make_enrollment(101, student_id=1, class_id=10, ay_id=1),
        _make_enrollment(102, student_id=2, class_id=10, ay_id=1),
        _make_enrollment(103, student_id=3, class_id=10, ay_id=1),
    ]
    source_result = MagicMock()
    source_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=source_enrollments))
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[classes_result, source_result])

    from app.repositories import enrollment_repository
    from app.services import enrollment_service

    original_get_active = enrollment_repository.get_active_enrollment
    original_create = enrollment_service.create_enrollment
    original_audit = promotion_service.audit_log

    enrollment_repository.get_active_enrollment = AsyncMock(return_value=None)
    enrollment_service.create_enrollment = AsyncMock(
        side_effect=[
            SimpleNamespace(id=201),
            SimpleNamespace(id=202),
            SimpleNamespace(id=203),
        ]
    )
    promotion_service.audit_log = AsyncMock()
    try:
        result = await promotion_service.execute_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={10: 20}, executed_by=99
        )
    finally:
        enrollment_repository.get_active_enrollment = original_get_active
        enrollment_service.create_enrollment = original_create
        promotion_service.audit_log = original_audit

    assert result.promoted_count == 3
    assert result.promoted_enrollment_ids == [201, 202, 203]
    assert result.skipped_count == 0
    assert result.error_count == 0
    assert result.errors == []


async def test_execute_skips_already_promoted_students() -> None:
    """Idempotency : si student déjà inscrit dans target_ay → skip silencieux."""
    target_class = _make_class(20, ay_id=2, name="5ème A", max_students=30)

    classes_result = MagicMock()
    classes_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[target_class]))
    )

    source_enrollments = [
        _make_enrollment(101, student_id=1, class_id=10, ay_id=1),
        _make_enrollment(102, student_id=2, class_id=10, ay_id=1),
    ]
    source_result = MagicMock()
    source_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=source_enrollments))
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[classes_result, source_result])

    from app.repositories import enrollment_repository
    from app.services import enrollment_service

    original_get_active = enrollment_repository.get_active_enrollment
    original_create = enrollment_service.create_enrollment
    original_audit = promotion_service.audit_log

    # student 1 déjà inscrit dans target_ay, student 2 pas encore
    enrollment_repository.get_active_enrollment = AsyncMock(
        side_effect=[
            SimpleNamespace(id=999),  # student 1 already promoted
            None,  # student 2 to promote
        ]
    )
    enrollment_service.create_enrollment = AsyncMock(return_value=SimpleNamespace(id=202))
    promotion_service.audit_log = AsyncMock()
    try:
        result = await promotion_service.execute_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={10: 20}, executed_by=99
        )
    finally:
        enrollment_repository.get_active_enrollment = original_get_active
        enrollment_service.create_enrollment = original_create
        promotion_service.audit_log = original_audit

    assert result.promoted_count == 1
    assert result.skipped_count == 1
    assert result.error_count == 0


async def test_execute_partial_success_on_capacity_overflow() -> None:
    """Si create_enrollment fail (capacity), partial-success reporting."""
    target_class = _make_class(20, ay_id=2, name="5ème A", max_students=2)

    classes_result = MagicMock()
    classes_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[target_class]))
    )

    source_enrollments = [
        _make_enrollment(101, student_id=1, class_id=10, ay_id=1),
        _make_enrollment(102, student_id=2, class_id=10, ay_id=1),
        _make_enrollment(103, student_id=3, class_id=10, ay_id=1),  # this one fails
    ]
    source_result = MagicMock()
    source_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=source_enrollments))
    )

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[classes_result, source_result])

    from app.repositories import enrollment_repository
    from app.services import enrollment_service

    original_get_active = enrollment_repository.get_active_enrollment
    original_create = enrollment_service.create_enrollment
    original_audit = promotion_service.audit_log

    enrollment_repository.get_active_enrollment = AsyncMock(return_value=None)
    enrollment_service.create_enrollment = AsyncMock(
        side_effect=[
            SimpleNamespace(id=201),
            SimpleNamespace(id=202),
            BusinessValidationError("Class 20 is full (2 students max)"),
        ]
    )
    promotion_service.audit_log = AsyncMock()
    try:
        result = await promotion_service.execute_promotion(
            db, source_ay_id=1, target_ay_id=2, class_mapping={10: 20}, executed_by=99
        )
    finally:
        enrollment_repository.get_active_enrollment = original_get_active
        enrollment_service.create_enrollment = original_create
        promotion_service.audit_log = original_audit

    assert result.promoted_count == 2
    assert result.promoted_enrollment_ids == [201, 202]
    assert result.error_count == 1
    assert result.errors[0].student_id == 3
    assert "full" in result.errors[0].reason
