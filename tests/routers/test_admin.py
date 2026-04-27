"""Tests des endpoints /admin (CRUD eleves, enseignants, personnel, classes, matieres, annees, niveaux)."""

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.schemas.admin import (
    AcademicYearListResponse,
    AcademicYearResponse,
    ClassListResponse,
    ClassResponse,
    LevelListResponse,
    LevelResponse,
    StaffListResponse,
    StaffResponse,
    StudentListResponse,
    StudentResponse,
    SubjectListResponse,
    SubjectResponse,
    TeacherListResponse,
    TeacherResponse,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now(UTC)
MOCK_USER = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


def _override_deps() -> None:
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear_deps() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_STUDENT = StudentResponse(
    id=1,
    first_name="Jean",
    last_name="Kouassi",
    birth_date=date(2010, 5, 15),
    genre="M",
    enrollment_number="ENR001",
    user_id=None,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_TEACHER = TeacherResponse(
    id=1,
    user_id=2,
    first_name="Marie",
    last_name="Diallo",
    speciality="Mathematiques",
    phone="+22507000000",
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_STAFF = StaffResponse(
    id=1,
    user_id=3,
    first_name="Paul",
    last_name="Kone",
    position="Secretaire",
    phone="+22508000000",
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_CLASS = ClassResponse(
    id=1,
    name="6eme A",
    level_id=1,
    series_id=None,
    academic_year_id=1,
    room_id=None,
    max_students=40,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_SUBJECT = SubjectResponse(
    id=1,
    name="Mathematiques",
    level_id=1,
    series_id=None,
    coefficient=3,
    hours_per_week=5,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_ACADEMIC_YEAR = AcademicYearResponse(
    id=1,
    name="2024-2025",
    start_date=date(2024, 9, 2),
    end_date=date(2025, 7, 4),
    is_current=True,
    created_at=NOW,
    updated_at=NOW,
)

SAMPLE_LEVEL = LevelResponse(
    id=1,
    name="6eme",
    order=1,
)

SVC = "app.routers.admin.admin_service"


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


def test_list_students_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_students",
            new_callable=AsyncMock,
            return_value=StudentListResponse(items=[SAMPLE_STUDENT], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/students")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["first_name"] == "Jean"


def test_create_student_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_student",
            new_callable=AsyncMock,
            return_value=SAMPLE_STUDENT,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/students",
                    json={
                        "first_name": "Jean",
                        "last_name": "Kouassi",
                        "email": "jean.kouassi@klassci.test",
                        "password": "TestPass@123",
                    },
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201
    assert resp.json()["id"] == 1


def test_create_student_missing_field() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post("/admin/students", json={"first_name": "Jean"})
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_get_student_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.get_student",
            new_callable=AsyncMock,
            return_value=SAMPLE_STUDENT,
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/students/1")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["enrollment_number"] == "ENR001"


def test_get_student_not_found() -> None:
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            f"{SVC}.get_student",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Student", 999),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/students/999")
    finally:
        _clear_deps()
    assert resp.status_code == 404


def test_update_student_success() -> None:
    updated = SAMPLE_STUDENT.model_copy(update={"first_name": "Jacques"})
    _override_deps()
    try:
        with patch(
            f"{SVC}.update_student",
            new_callable=AsyncMock,
            return_value=updated,
        ):
            with TestClient(app) as client:
                resp = client.patch("/admin/students/1", json={"first_name": "Jacques"})
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Jacques"


def test_delete_student_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_student",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/students/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


def test_students_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/admin/students")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Teachers
# ---------------------------------------------------------------------------


def test_list_teachers_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_teachers",
            new_callable=AsyncMock,
            return_value=TeacherListResponse(items=[SAMPLE_TEACHER], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/teachers")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["speciality"] == "Mathematiques"


def test_create_teacher_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_teacher",
            new_callable=AsyncMock,
            return_value=SAMPLE_TEACHER,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/teachers",
                    json={
                        "first_name": "Marie",
                        "last_name": "Diallo",
                        "email": "marie.diallo@klassci.test",
                        "password": "TestPass@123",
                    },
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201


def test_get_teacher_not_found() -> None:
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            f"{SVC}.get_teacher",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Teacher", 999),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/teachers/999")
    finally:
        _clear_deps()
    assert resp.status_code == 404


def test_delete_teacher_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_teacher",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/teachers/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------


def test_list_staff_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_staff",
            new_callable=AsyncMock,
            return_value=StaffListResponse(items=[SAMPLE_STAFF], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/staff")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["position"] == "Secretaire"


def test_create_staff_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_staff",
            new_callable=AsyncMock,
            return_value=SAMPLE_STAFF,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/staff",
                    json={"first_name": "Paul", "last_name": "Kone", "user_id": 3},
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201


def test_delete_staff_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_staff",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/staff/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


def test_list_classes_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_classes",
            new_callable=AsyncMock,
            return_value=ClassListResponse(items=[SAMPLE_CLASS], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/classes")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["name"] == "6eme A"


def test_list_classes_with_filters() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_classes",
            new_callable=AsyncMock,
            return_value=ClassListResponse(items=[], total=0, page=1, size=20),
        ) as mock_list:
            with TestClient(app) as client:
                resp = client.get("/admin/classes?level_id=1&academic_year_id=1")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs["level_id"] == 1
    assert call_kwargs["academic_year_id"] == 1


def test_create_class_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_class",
            new_callable=AsyncMock,
            return_value=SAMPLE_CLASS,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/classes",
                    json={"name": "6eme A", "level_id": 1, "academic_year_id": 1},
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201
    assert resp.json()["max_students"] == 40


def test_delete_class_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_class",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/classes/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


def test_list_subjects_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_subjects",
            new_callable=AsyncMock,
            return_value=SubjectListResponse(items=[SAMPLE_SUBJECT], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/subjects")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["coefficient"] == 3


def test_list_subjects_filtered_by_class_id() -> None:
    """GET /admin/subjects?class_id=N → 200 et le param est forwardé au service.

    Le filtre applique le prédicat curriculum (level + série + null-semantics)
    pour ne montrer que les matières enseignées dans la classe sélectionnée.
    """
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_subjects",
            new_callable=AsyncMock,
            return_value=SubjectListResponse(items=[SAMPLE_SUBJECT], total=1, page=1, size=20),
        ) as mock_svc:
            with TestClient(app) as client:
                resp = client.get("/admin/subjects?class_id=42")
        mock_svc.assert_awaited_once()
        kwargs = mock_svc.call_args.kwargs
        assert kwargs.get("class_id") == 42
        assert kwargs.get("level_id") is None
    finally:
        _clear_deps()
    assert resp.status_code == 200


def test_list_subjects_class_and_level_both_returns_422() -> None:
    """GET /admin/subjects?class_id=N&level_id=M → 422 (mutuellement exclusifs).

    Si les deux filtres sont passés simultanément, le service refuse plutôt que
    de deviner lequel applique — l'API doit être sans ambiguïté pour les clients.
    """
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.get("/admin/subjects?class_id=1&level_id=2")
    finally:
        _clear_deps()
    assert resp.status_code == 422
    detail = resp.json().get("detail", "")
    assert "class_id" in detail or "level_id" in detail


def test_create_subject_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_subject",
            new_callable=AsyncMock,
            return_value=SAMPLE_SUBJECT,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/subjects",
                    json={"name": "Mathematiques", "coefficient": 3, "hours_per_week": 5},
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201


def test_create_subject_invalid_coefficient() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/admin/subjects",
                json={"name": "Bad", "coefficient": 0},
            )
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_delete_subject_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_subject",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/subjects/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Academic Years
# ---------------------------------------------------------------------------


def test_list_academic_years_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_academic_years",
            new_callable=AsyncMock,
            return_value=AcademicYearListResponse(
                items=[SAMPLE_ACADEMIC_YEAR], total=1, page=1, size=20
            ),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/academic-years")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["name"] == "2024-2025"


def test_create_academic_year_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_academic_year",
            new_callable=AsyncMock,
            return_value=SAMPLE_ACADEMIC_YEAR,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/academic-years",
                    json={
                        "name": "2024-2025",
                        "start_date": "2024-09-02",
                        "end_date": "2025-07-04",
                        "is_current": True,
                    },
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201
    assert resp.json()["is_current"] is True


def test_create_academic_year_invalid_dates() -> None:
    _override_deps()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/admin/academic-years",
                json={
                    "name": "bad",
                    "start_date": "2025-09-01",
                    "end_date": "2024-07-01",
                },
            )
    finally:
        _clear_deps()
    assert resp.status_code == 422


def test_delete_academic_year_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_academic_year",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/academic-years/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Levels
# ---------------------------------------------------------------------------


def test_list_levels_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.list_levels",
            new_callable=AsyncMock,
            return_value=LevelListResponse(items=[SAMPLE_LEVEL], total=1, page=1, size=20),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/levels")
    finally:
        _clear_deps()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["name"] == "6eme"


def test_create_level_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.create_level",
            new_callable=AsyncMock,
            return_value=SAMPLE_LEVEL,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/admin/levels",
                    json={"name": "6eme", "order": 1},
                )
    finally:
        _clear_deps()
    assert resp.status_code == 201
    assert resp.json()["order"] == 1


def test_delete_level_success() -> None:
    _override_deps()
    try:
        with patch(
            f"{SVC}.delete_level",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with TestClient(app) as client:
                resp = client.delete("/admin/levels/1")
    finally:
        _clear_deps()
    assert resp.status_code == 204


def test_get_level_not_found() -> None:
    from app.core.exceptions import NotFoundError

    _override_deps()
    try:
        with patch(
            f"{SVC}.get_level",
            new_callable=AsyncMock,
            side_effect=NotFoundError("Level", 999),
        ):
            with TestClient(app) as client:
                resp = client.get("/admin/levels/999")
    finally:
        _clear_deps()
    assert resp.status_code == 404
