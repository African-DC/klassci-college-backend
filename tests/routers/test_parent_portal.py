"""Tests des endpoints /parent."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.parent_portal import (
    BulletinDetail,
    ChildBulletinsResponse,
    ChildEnrollmentInfo,
    ChildFeesResponse,
    ChildGradesResponse,
    ChildrenListResponse,
    ChildResponse,
    FeeDetail,
    GradeDetail,
    PaymentDetail,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)

MOCK_USER = TokenData(user_id=10, tenant_id="local", email="parent@college.ci")

SAMPLE_CHILD = ChildResponse(
    id=42,
    first_name="Aya",
    last_name="Koné",
    birth_date=None,
    enrollment_number="STU-001",
    relationship_type="mother",
    enrollment=ChildEnrollmentInfo(
        enrollment_id=1,
        class_id=3,
        class_name="6ème A",
        academic_year_name="2025-2026",
        status="valide",
    ),
)

SAMPLE_CHILDREN_LIST = ChildrenListResponse(children=[SAMPLE_CHILD])

SAMPLE_GRADE = GradeDetail(
    id=1,
    value=Decimal("14.50"),
    status="entered",
    evaluation_title="Devoir 1 Maths",
    evaluation_type="devoir",
    evaluation_date=NOW.date(),
    subject_name="Mathématiques",
    coefficient=2,
    trimester=1,
)

SAMPLE_GRADES_RESPONSE = ChildGradesResponse(student_id=42, grades=[SAMPLE_GRADE])

SAMPLE_PAYMENT = PaymentDetail(
    id=1,
    amount=Decimal("50000.00"),
    method="mobile_money",
    status="completed",
    reference="PAY-001",
    created_at=NOW,
)

SAMPLE_FEE = FeeDetail(
    id=1,
    amount=Decimal("100000.00"),
    status="partial",
    category_name="Inscription",
    payments=[SAMPLE_PAYMENT],
)

SAMPLE_FEES_RESPONSE = ChildFeesResponse(
    student_id=42,
    enrollment_id=1,
    fees=[SAMPLE_FEE],
    total_due=Decimal("100000.00"),
    total_paid=Decimal("50000.00"),
)

SAMPLE_BULLETIN = BulletinDetail(
    id=1,
    trimester=1,
    average=Decimal("13.50"),
    rank=5,
    mention="AB",
    class_name="6ème A",
    academic_year_name="2025-2026",
    is_published=True,
    generated_at=NOW,
)

SAMPLE_BULLETINS_RESPONSE = ChildBulletinsResponse(student_id=42, bulletins=[SAMPLE_BULLETIN])


def _override_deps() -> None:
    """Surcharge les dépendances d'auth et DB pour les tests."""
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /parent/children
# ---------------------------------------------------------------------------


def test_list_children_success() -> None:
    """GET /parent/children → 200 + liste d'enfants."""
    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.list_children",
            new_callable=AsyncMock,
            return_value=SAMPLE_CHILDREN_LIST,
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["children"]) == 1
    assert body["children"][0]["id"] == 42
    assert body["children"][0]["first_name"] == "Aya"
    assert body["children"][0]["enrollment"]["class_name"] == "6ème A"


def test_list_children_unauthenticated() -> None:
    """GET /parent/children sans token → 401."""
    with TestClient(app) as client:
        resp = client.get("/parent/children")
    assert resp.status_code == 401


def test_list_children_no_parent_profile() -> None:
    """GET /parent/children avec user sans profil parent → 404."""
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.list_children",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Parent", 10),
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children")
    finally:
        _clear_deps()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /parent/children/{student_id}/grades
# ---------------------------------------------------------------------------


def test_get_child_grades_success() -> None:
    """GET /parent/children/42/grades → 200 + notes."""
    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_grades",
            new_callable=AsyncMock,
            return_value=SAMPLE_GRADES_RESPONSE,
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/42/grades")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == 42
    assert len(body["grades"]) == 1
    assert body["grades"][0]["evaluation_title"] == "Devoir 1 Maths"


def test_get_child_grades_with_trimester_filter() -> None:
    """GET /parent/children/42/grades?trimester=1 → filtre trimestre."""
    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_grades",
            new_callable=AsyncMock,
            return_value=SAMPLE_GRADES_RESPONSE,
        ) as mock_grades:
            with TestClient(app) as client:
                resp = client.get("/parent/children/42/grades?trimester=1")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    mock_grades.assert_called_once()
    call_kwargs = mock_grades.call_args.kwargs
    assert call_kwargs["trimester"] == 1


def test_get_child_grades_permission_denied() -> None:
    """GET /parent/children/99/grades pour un enfant non lié → 403."""
    from app.core.exceptions import PermissionDeniedError

    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_grades",
            new_callable=AsyncMock,
            side_effect=PermissionDeniedError("access to this student"),
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/99/grades")
    finally:
        _clear_deps()

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /parent/children/{student_id}/fees
# ---------------------------------------------------------------------------


def test_get_child_fees_success() -> None:
    """GET /parent/children/42/fees → 200 + frais."""
    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_fees",
            new_callable=AsyncMock,
            return_value=SAMPLE_FEES_RESPONSE,
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/42/fees")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == 42
    assert body["enrollment_id"] == 1
    assert len(body["fees"]) == 1
    assert body["total_due"] == "100000.00"
    assert body["total_paid"] == "50000.00"


def test_get_child_fees_permission_denied() -> None:
    """GET /parent/children/99/fees pour un enfant non lié → 403."""
    from app.core.exceptions import PermissionDeniedError

    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_fees",
            new_callable=AsyncMock,
            side_effect=PermissionDeniedError("access to this student"),
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/99/fees")
    finally:
        _clear_deps()

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /parent/children/{student_id}/bulletins
# ---------------------------------------------------------------------------


def test_get_child_bulletins_success() -> None:
    """GET /parent/children/42/bulletins → 200 + bulletins."""
    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_bulletins",
            new_callable=AsyncMock,
            return_value=SAMPLE_BULLETINS_RESPONSE,
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/42/bulletins")
    finally:
        _clear_deps()

    assert resp.status_code == 200
    body = resp.json()
    assert body["student_id"] == 42
    assert len(body["bulletins"]) == 1
    assert body["bulletins"][0]["trimester"] == 1
    assert body["bulletins"][0]["mention"] == "AB"


def test_get_child_bulletins_permission_denied() -> None:
    """GET /parent/children/99/bulletins pour un enfant non lié → 403."""
    from app.core.exceptions import PermissionDeniedError

    _override_deps()
    try:
        with patch(
            "app.routers.parent_portal.parent_portal_service.get_child_bulletins",
            new_callable=AsyncMock,
            side_effect=PermissionDeniedError("access to this student"),
        ):
            with TestClient(app) as client:
                resp = client.get("/parent/children/99/bulletins")
    finally:
        _clear_deps()

    assert resp.status_code == 403
