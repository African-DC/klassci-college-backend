"""Smoke tests — import et structure de tous les modèles SQLAlchemy."""

import pytest
from sqlalchemy import inspect

from app.core.database import Base


def test_all_models_importable() -> None:
    """Tous les modèles doivent pouvoir être importés sans erreur."""
    import app.models  # noqa: F401 — déclenche l'enregistrement dans Base.metadata


def test_base_metadata_contains_expected_tables() -> None:
    """Base.metadata doit contenir toutes les tables du schéma après import."""
    import app.models  # noqa: F401

    expected = {
        # Référentiels
        "academic_years",
        "levels",
        "series",
        "rooms",
        "school_settings",
        # Users
        "users",
        "staff_profiles",
        "teacher_profiles",
        "students",
        "parents",
        "parent_students",
        # Auth
        "roles",
        "permissions",
        "role_permissions",
        "user_roles",
        # Inscriptions et frais
        "enrollments",
        "documents",
        "student_options",
        "fee_categories",
        "fee_variants",
        "optional_fee_options",
        "enrollment_fees",
        "payments",
        # Classes / matières
        "classes",
        "subjects",
        # Emploi du temps
        "timetables",
        "timetable_slots",
        "teacher_availabilities",
        # Notes
        "evaluations",
        "grades",
        "bulletins",
        # Présences
        "attendance_contexts",
        "attendance_records",
        # Notifications
        "notifications",
        "notification_templates",
        # Messagerie
        "messages",
        # Audit
        "audit_logs",
    }

    registered = set(Base.metadata.tables.keys())
    missing = expected - registered
    assert not missing, f"Tables manquantes dans Base.metadata : {missing}"


@pytest.mark.parametrize(
    "model_path,table_name",
    [
        ("app.models.academic.AcademicYear", "academic_years"),
        ("app.models.academic.Class", "classes"),
        ("app.models.academic.Subject", "subjects"),
        ("app.models.user.User", "users"),
        ("app.models.user.Student", "students"),
        ("app.models.user.TeacherProfile", "teacher_profiles"),
        ("app.models.enrollment.Enrollment", "enrollments"),
        ("app.models.fee.Payment", "payments"),
        ("app.models.timetable.TimetableSlot", "timetable_slots"),
        ("app.models.grade.Grade", "grades"),
        ("app.models.attendance.AttendanceRecord", "attendance_records"),
        ("app.models.permission.Permission", "permissions"),
        ("app.models.notification.Notification", "notifications"),
        ("app.models.message.Message", "messages"),
    ],
)
def test_model_tablename(model_path: str, table_name: str) -> None:
    """Chaque modèle doit déclarer le bon __tablename__."""
    module_path, class_name = model_path.rsplit(".", 1)
    import importlib

    module = importlib.import_module(module_path)
    model_cls = getattr(module, class_name)
    assert model_cls.__tablename__ == table_name


def test_timestamp_mixin_on_key_models() -> None:
    """Les modèles sensibles doivent avoir created_at et updated_at."""
    from app.models.enrollment import Enrollment
    from app.models.fee import Payment
    from app.models.grade import Grade
    from app.models.user import User

    for model_cls in (User, Enrollment, Payment, Grade):
        cols = {c.key for c in inspect(model_cls).mapper.column_attrs}
        assert "created_at" in cols, f"{model_cls.__name__} manque created_at"
        assert "updated_at" in cols, f"{model_cls.__name__} manque updated_at"


def test_decimal_columns_on_financial_models() -> None:
    """Les montants doivent être Numeric(15,2) — jamais Float."""
    from sqlalchemy import Numeric

    from app.models.fee import EnrollmentFee, FeeVariant, OptionalFeeOption, Payment

    for model_cls in (Payment, FeeVariant, OptionalFeeOption, EnrollmentFee):
        table = Base.metadata.tables[model_cls.__tablename__]
        amount_col = table.c["amount"]
        assert isinstance(
            amount_col.type, Numeric
        ), f"{model_cls.__name__}.amount doit être Numeric, pas {type(amount_col.type)}"
        assert amount_col.type.precision == 15
        assert amount_col.type.scale == 2


def test_audit_log_registered() -> None:
    """AuditLog doit être enregistré dans Base.metadata."""
    import app.models  # noqa: F401

    assert "audit_logs" in Base.metadata.tables
