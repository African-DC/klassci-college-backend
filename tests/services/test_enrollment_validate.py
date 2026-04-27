"""Tests pour `enrollment_service.validate_enrollment` — transition guard.

Endpoint dédié `POST /enrollments/{id}/validate` introduit pour le redesign
queue-first de `/admin/enrollments` (cycle 1 du roadmap, plan A).

Le test exerce la logique du guard sans toucher la DB : on mock
`repo.get_enrollment_by_id` pour retourner un Enrollment au statut désiré,
on mock le commit, et on vérifie que le service refuse les transitions
invalides avec un message FR clair.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.models.enrollment import EnrollmentStatus
from app.services import enrollment_service


def _make_enrollment(status: EnrollmentStatus, enrollment_id: int = 1) -> SimpleNamespace:
    """Stand-in Enrollment ORM avec les champs touchés par _to_response."""
    return SimpleNamespace(
        id=enrollment_id,
        student_id=42,
        class_id=3,
        academic_year_id=1,
        academic_year=SimpleNamespace(id=1, name="2025-2026"),
        status=status,
        notes=None,
        created_by=1,
        enrollment_fees=[],
        created_at=None,
        updated_at=None,
    )


async def test_validate_enrollment_not_found() -> None:
    """ID inconnu → NotFoundError."""
    from app.repositories import enrollment_repository

    async def fake_get(db, enrollment_id):
        return None

    original = enrollment_repository.get_enrollment_by_id
    enrollment_repository.get_enrollment_by_id = fake_get
    try:
        with pytest.raises(NotFoundError):
            await enrollment_service.validate_enrollment(AsyncMock(), 999, validated_by=1)
    finally:
        enrollment_repository.get_enrollment_by_id = original


async def test_validate_enrollment_already_validated_returns_422() -> None:
    """Statut déjà VALIDE → BusinessValidationError avec message FR explicite."""
    from app.repositories import enrollment_repository

    enrollment = _make_enrollment(EnrollmentStatus.VALIDE)

    async def fake_get(db, enrollment_id):
        return enrollment

    original = enrollment_repository.get_enrollment_by_id
    enrollment_repository.get_enrollment_by_id = fake_get
    try:
        with pytest.raises(BusinessValidationError) as exc_info:
            await enrollment_service.validate_enrollment(AsyncMock(), 1, validated_by=1)
    finally:
        enrollment_repository.get_enrollment_by_id = original

    assert exc_info.value.status_code == 422
    assert "déjà validée" in exc_info.value.detail


@pytest.mark.parametrize("status", [EnrollmentStatus.REJETE, EnrollmentStatus.ANNULE])
async def test_validate_enrollment_blocked_for_terminal_statuses(
    status: EnrollmentStatus,
) -> None:
    """Statuts terminaux (rejeté, annulé) → BusinessValidationError.

    Les transitions valides sont uniquement prospect → valide et en_validation
    → valide. Toute autre transition (rejeté → valide, annulé → valide) doit
    être refusée pour préserver l'historique de décision.
    """
    from app.repositories import enrollment_repository

    enrollment = _make_enrollment(status)

    async def fake_get(db, enrollment_id):
        return enrollment

    original = enrollment_repository.get_enrollment_by_id
    enrollment_repository.get_enrollment_by_id = fake_get
    try:
        with pytest.raises(BusinessValidationError) as exc_info:
            await enrollment_service.validate_enrollment(AsyncMock(), 1, validated_by=1)
    finally:
        enrollment_repository.get_enrollment_by_id = original

    assert exc_info.value.status_code == 422
    assert status.value in exc_info.value.detail


@pytest.mark.parametrize(
    "from_status",
    [EnrollmentStatus.PROSPECT, EnrollmentStatus.EN_VALIDATION],
)
async def test_validate_enrollment_happy_path_transitions(
    from_status: EnrollmentStatus,
) -> None:
    """prospect / en_validation → valide : audit log enregistré + commit."""
    from app.repositories import enrollment_repository

    enrollment = _make_enrollment(from_status)

    captured_audit: dict = {}
    db = AsyncMock()
    nested_ctx = MagicMock()
    nested_ctx.__aenter__ = AsyncMock(return_value=None)
    nested_ctx.__aexit__ = AsyncMock(return_value=None)
    db.begin_nested = MagicMock(return_value=nested_ctx)

    async def fake_get(d, enrollment_id):
        return enrollment

    async def fake_update(d, e, **kwargs):
        if "status" in kwargs:
            e.status = kwargs["status"]
        return e

    async def fake_audit_log(*args, **kwargs):
        captured_audit.update(kwargs)

    original_get = enrollment_repository.get_enrollment_by_id
    original_update = enrollment_repository.update_enrollment
    original_audit = enrollment_service.audit_log
    enrollment_repository.get_enrollment_by_id = fake_get
    enrollment_repository.update_enrollment = fake_update
    enrollment_service.audit_log = fake_audit_log
    try:
        result = await enrollment_service.validate_enrollment(db, 1, validated_by=7)
    finally:
        enrollment_repository.get_enrollment_by_id = original_get
        enrollment_repository.update_enrollment = original_update
        enrollment_service.audit_log = original_audit

    assert result.status == EnrollmentStatus.VALIDE
    assert captured_audit["entity_type"] == "enrollment"
    assert captured_audit["user_id"] == 7
    assert captured_audit["old_values"]["status"] == from_status.value
    assert captured_audit["new_values"]["status"] == EnrollmentStatus.VALIDE.value
    assert captured_audit["new_values"]["transition"] == "validate"
