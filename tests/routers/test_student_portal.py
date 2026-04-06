"""Tests des endpoints /student (portail eleve)."""

from datetime import UTC, datetime, time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.exceptions import NotFoundError
from app.core.redis import get_redis
from app.main import app
from app.schemas.student_portal import (
    BulletinResponse,
    EnrollmentFeeResponse,
    EvaluationDetail,
    PaymentResponse,
    StudentBulletinsListResponse,
    StudentFeesResponse,
    StudentGradeResponse,
    StudentGradesListResponse,
    StudentProfileResponse,
    StudentTimetableResponse,
    TimetableSlotResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

MOCK_USER = TokenData(user_id=1, tenant_id="local", email="student@college.ci")


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_GRADES = StudentGradesListResponse(
    items=[
        StudentGradeResponse(
            id=1,
            value=Decimal("15.50"),
            status="entered",
            evaluation=EvaluationDetail(
                id=10,
                title="Controle Maths T1",
                type="controle",
                date=NOW.date(),
                coefficient=2,
                trimester=1,
                subject_name="Mathematiques",
            ),
        ),
    ],
    total=1,
)

SAMPLE_TIMETABLE = StudentTimetableResponse(
    class_name="6eme A",
    slots=[
        TimetableSlotResponse(
            id=1,
            day="monday",
            start_time=time(8, 0),
            end_time=time(10, 0),
            subject_name="Mathematiques",
            teacher_name="Jean Dupont",
            room_name="Salle 101",
        ),
    ],
)

SAMPLE_FEES = StudentFeesResponse(
    total_due=Decimal("150000.00"),
    total_paid=Decimal("75000.00"),
    balance=Decimal("75000.00"),
    fees=[
        EnrollmentFeeResponse(
            id=1,
            fee_category_name="Scolarite T1",
            amount=Decimal("150000.00"),
            status="partial",
            payments=[
                PaymentResponse(
                    id=1,
                    amount=Decimal("75000.00"),
                    method="mobile_money",
                    status="completed",
                    reference="PAY-001",
                    created_at=NOW,
                ),
            ],
        ),
    ],
)

SAMPLE_BULLETINS = StudentBulletinsListResponse(
    items=[
        BulletinResponse(
            id=1,
            trimester=1,
            average=Decimal("14.25"),
            rank=3,
            mention="B",
            class_name="6eme A",
            academic_year_name="2025-2026",
            file_url="/bulletins/1.pdf",
            generated_at=NOW,
        ),
    ],
    total=1,
)

SAMPLE_PROFILE = StudentProfileResponse(
    id=42,
    first_name="Awa",
    last_name="Kone",
    birth_date=None,
    genre="F",
    enrollment_number="STU-001",
    email="student@college.ci",
    class_name="6eme A",
    class_id=3,
    enrollment_status="valide",
    academic_year_name="2025-2026",
)


# ---------------------------------------------------------------------------
# GET /student/grades
# ---------------------------------------------------------------------------


def test_get_grades_success() -> None:
    """GET /student/grades -> 200 + liste de notes."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_grades",
            new_callable=AsyncMock,
            return_value=SAMPLE_GRADES,
        ):
            with TestClient(app) as client:
                resp = client.get("/student/grades")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["value"] == "15.50"
    assert body["items"][0]["evaluation"]["subject_name"] == "Mathematiques"


def test_get_grades_with_filters() -> None:
    """GET /student/grades?trimester=1&subject_id=5 -> filtres transmis."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_grades",
            new_callable=AsyncMock,
            return_value=SAMPLE_GRADES,
        ) as mock_fn:
            with TestClient(app) as client:
                resp = client.get("/student/grades?trimester=1&subject_id=5")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_fn.assert_called_once()
    _, kwargs = mock_fn.call_args
    assert kwargs["trimester"] == 1
    assert kwargs["subject_id"] == 5


def test_get_grades_student_not_found() -> None:
    """GET /student/grades sans profil eleve -> 404."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_grades",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student profile not found for this user", 1),
        ):
            with TestClient(app) as client:
                resp = client.get("/student/grades")
    finally:
        _clear_deps()

    assert resp.status_code == 404


def test_get_grades_unauthenticated() -> None:
    """GET /student/grades sans token -> 401."""
    with TestClient(app) as client:
        resp = client.get("/student/grades")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /student/timetable
# ---------------------------------------------------------------------------


def test_get_timetable_success() -> None:
    """GET /student/timetable -> 200 + emploi du temps."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_timetable",
            new_callable=AsyncMock,
            return_value=SAMPLE_TIMETABLE,
        ):
            with TestClient(app) as client:
                resp = client.get("/student/timetable")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["class_name"] == "6eme A"
    assert len(body["slots"]) == 1
    assert body["slots"][0]["subject_name"] == "Mathematiques"


def test_get_timetable_no_enrollment() -> None:
    """GET /student/timetable sans inscription active -> 404."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_timetable",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Active enrollment not found for student", 42),
        ):
            with TestClient(app) as client:
                resp = client.get("/student/timetable")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /student/fees
# ---------------------------------------------------------------------------


def test_get_fees_success() -> None:
    """GET /student/fees -> 200 + frais et paiements."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_fees",
            new_callable=AsyncMock,
            return_value=SAMPLE_FEES,
        ):
            with TestClient(app) as client:
                resp = client.get("/student/fees")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_due"] == "150000.00"
    assert body["total_paid"] == "75000.00"
    assert body["balance"] == "75000.00"
    assert len(body["fees"]) == 1
    assert body["fees"][0]["fee_category_name"] == "Scolarite T1"


def test_get_fees_no_enrollment() -> None:
    """GET /student/fees sans inscription active -> 404."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_fees",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Active enrollment not found for student", 42),
        ):
            with TestClient(app) as client:
                resp = client.get("/student/fees")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /student/bulletins
# ---------------------------------------------------------------------------


def test_get_bulletins_success() -> None:
    """GET /student/bulletins -> 200 + bulletins publies."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_bulletins",
            new_callable=AsyncMock,
            return_value=SAMPLE_BULLETINS,
        ):
            with TestClient(app) as client:
                resp = client.get("/student/bulletins")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["average"] == "14.25"
    assert body["items"][0]["mention"] == "B"


# ---------------------------------------------------------------------------
# GET /student/profile
# ---------------------------------------------------------------------------


def test_get_profile_success() -> None:
    """GET /student/profile -> 200 + profil complet."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_profile",
            new_callable=AsyncMock,
            return_value=SAMPLE_PROFILE,
        ):
            with TestClient(app) as client:
                resp = client.get("/student/profile")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == "Awa"
    assert body["last_name"] == "Kone"
    assert body["class_name"] == "6eme A"
    assert body["enrollment_status"] == "valide"


def test_get_profile_not_found() -> None:
    """GET /student/profile sans profil eleve -> 404."""
    _override_deps()
    try:
        with patch(
            "app.routers.student_portal.student_portal_service.get_profile",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student profile not found for this user", 1),
        ):
            with TestClient(app) as client:
                resp = client.get("/student/profile")
    finally:
        _clear_deps()

    assert resp.status_code == 404
