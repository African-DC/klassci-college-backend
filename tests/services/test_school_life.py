"""Règles métier des actes de vie scolaire.

Deux garde-fous portent tout le reste : un rattrapage ne s'autorise que sur une
évaluation réellement manquée, et une convocation ne se date jamais dans le
passé. Sans eux, le billet d'annulation de zéro devient un moyen d'effacer une
mauvaise note, et la convocation un moyen de couvrir une réunion qui a déjà eu
lieu.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.core.exceptions import BusinessValidationError
from app.models.attendance import AttendanceStatus
from app.models.grade import GradeStatus
from app.schemas.school_life import (
    ParentSummonsCreate,
    RetakeAuthorizationCreate,
    SummonsOutcomeUpdate,
)
from app.services.school_life import entry_slip_service
from app.services.school_life.retake_service import _validate_targets

# ---------------------------------------------------------------------------
# Stand-ins
# ---------------------------------------------------------------------------


def _grade(
    evaluation_id: int,
    status: GradeStatus,
    *,
    trimester: int = 1,
    title: str = "Devoir n°1",
) -> SimpleNamespace:
    """Note d'élève accompagnée de son évaluation, comme le repo la renvoie."""
    return SimpleNamespace(
        id=evaluation_id * 10,
        evaluation_id=evaluation_id,
        status=status,
        value=None,
        evaluation=SimpleNamespace(
            id=evaluation_id, title=title, trimester=trimester, coefficient=2
        ),
    )


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        student=SimpleNamespace(id=42, first_name="Aminata", last_name="Traoré"),
        class_name="6ème B",
        academic_year_id=1,
        academic_year_name="2025-2026",
        school_settings={"school_name": "Collège d'Excellence"},
        student_payload=lambda: {"first_name": "Aminata", "last_name": "Traoré"},
    )


# ---------------------------------------------------------------------------
# Billet d'annulation de zéro — un rattrapage suppose une épreuve manquée
# ---------------------------------------------------------------------------


def test_retake_refused_when_evaluation_was_actually_sat() -> None:
    """Une note saisie n'est pas une épreuve manquée : rien à rattraper."""
    grades = [_grade(7, GradeStatus.ENTERED, title="Devoir de maths")]
    with pytest.raises(BusinessValidationError) as excinfo:
        _validate_targets(grades, evaluation_ids=[7], context=_context())
    message = str(excinfo.value)
    assert "réellement manquée" in message
    assert "Devoir de maths" in message


def test_retake_refused_when_evaluation_not_yet_graded() -> None:
    """Une copie pas encore corrigée n'est pas une absence non plus."""
    grades = [_grade(7, GradeStatus.PENDING)]
    with pytest.raises(BusinessValidationError):
        _validate_targets(grades, evaluation_ids=[7], context=_context())


def test_retake_accepted_on_missed_evaluation_returns_its_trimester() -> None:
    """Sur une absence marquée, le billet passe et hérite du trimestre visé."""
    grades = [_grade(7, GradeStatus.ABSENT, trimester=2)]
    assert _validate_targets(grades, evaluation_ids=[7], context=_context()) == 2


def test_retake_refused_when_student_not_attached_to_evaluation() -> None:
    """Viser une évaluation d'une autre classe se dit, plutôt que de s'ignorer."""
    grades = [_grade(7, GradeStatus.ABSENT)]
    with pytest.raises(BusinessValidationError) as excinfo:
        _validate_targets(grades, evaluation_ids=[7, 99], context=_context())
    assert "99" in str(excinfo.value)


def test_retake_refused_across_two_trimesters() -> None:
    """Un billet couvre un trimestre : deux trimestres, deux billets."""
    grades = [
        _grade(7, GradeStatus.ABSENT, trimester=1),
        _grade(8, GradeStatus.ABSENT, trimester=2),
    ]
    with pytest.raises(BusinessValidationError) as excinfo:
        _validate_targets(grades, evaluation_ids=[7, 8], context=_context())
    assert "un seul trimestre" in str(excinfo.value)


def test_retake_payload_refuses_reversed_period() -> None:
    with pytest.raises(ValidationError):
        RetakeAuthorizationCreate(
            student_id=42,
            period_start=date(2026, 5, 20),
            period_end=date(2026, 5, 18),
            reason="Hospitalisation",
            evaluation_ids=[7],
        )


def test_retake_payload_refuses_duplicate_evaluations() -> None:
    with pytest.raises(ValidationError):
        RetakeAuthorizationCreate(
            student_id=42,
            period_start=date(2026, 5, 18),
            period_end=date(2026, 5, 20),
            reason="Hospitalisation",
            evaluation_ids=[7, 7],
        )


def test_retake_payload_requires_at_least_one_evaluation() -> None:
    """Un billet sans cible ne rouvrirait rien : autant ne pas l'éditer."""
    with pytest.raises(ValidationError):
        RetakeAuthorizationCreate(
            student_id=42,
            period_start=date(2026, 5, 18),
            period_end=date(2026, 5, 20),
            reason="Hospitalisation",
            evaluation_ids=[],
        )


# ---------------------------------------------------------------------------
# Convocation — jamais dans le passé, jamais anonyme
# ---------------------------------------------------------------------------


def test_summons_refuses_a_past_date() -> None:
    """Antidater une convocation reviendrait à couvrir un rendez-vous passé."""
    with pytest.raises(ValidationError) as excinfo:
        ParentSummonsCreate(
            student_id=42,
            parent_name="Mme Traoré",
            summons_date=date.today() - timedelta(days=1),
            summons_time=time(10, 0),
            reason="Absences répétées",
        )
    assert "aujourd'hui ou à venir" in str(excinfo.value)


def test_summons_accepts_today() -> None:
    """Convoquer pour le jour même est courant : le parent est au guichet."""
    payload = ParentSummonsCreate(
        student_id=42,
        parent_name="Mme Traoré",
        summons_date=date.today(),
        summons_time=time(10, 0),
        reason="Absences répétées",
    )
    assert payload.summons_date == date.today()


def test_summons_accepts_a_future_date() -> None:
    payload = ParentSummonsCreate(
        student_id=42,
        parent_id=7,
        summons_date=date.today() + timedelta(days=3),
        summons_time=time(15, 30),
        reason="Comportement en classe",
    )
    assert payload.parent_id == 7


def test_summons_requires_a_named_guardian() -> None:
    """Sans fiche parent ni nom dicté, la convocation sortirait au nom de personne."""
    with pytest.raises(ValidationError) as excinfo:
        ParentSummonsCreate(
            student_id=42,
            summons_date=date.today() + timedelta(days=1),
            summons_time=time(9, 0),
            reason="Absences répétées",
        )
    assert "tuteur convoqué" in str(excinfo.value)


def test_summons_outcome_rejects_an_unknown_value() -> None:
    with pytest.raises(ValidationError):
        SummonsOutcomeUpdate(outcome="peut-etre")


@pytest.mark.parametrize("outcome", ["pending", "attended", "missed"])
def test_summons_outcome_accepts_the_three_known_suites(outcome: str) -> None:
    assert SummonsOutcomeUpdate(outcome=outcome).outcome == outcome


# ---------------------------------------------------------------------------
# Billet d'entrée — ferme une absence, n'en invente pas
# ---------------------------------------------------------------------------


def _attendance_record(status: AttendanceStatus, absence_day: date) -> SimpleNamespace:
    return SimpleNamespace(
        id=77,
        student_id=42,
        status=status,
        notes=None,
        context=SimpleNamespace(date=absence_day),
    )


def _patch_entry_slip(monkeypatch: pytest.MonkeyPatch, record: SimpleNamespace) -> None:
    """Isole le service de la base : on teste sa règle, pas SQLAlchemy."""
    monkeypatch.setattr(entry_slip_service, "_load_record", AsyncMock(return_value=record))
    monkeypatch.setattr(
        entry_slip_service, "load_student_context", AsyncMock(return_value=_context())
    )
    monkeypatch.setattr(entry_slip_service, "audit_log", AsyncMock(return_value=None))


async def test_entry_slip_refused_on_a_student_marked_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rien à régulariser sur une séance où l'élève était là."""
    record = _attendance_record(AttendanceStatus.PRESENT, date(2026, 5, 18))
    _patch_entry_slip(monkeypatch, record)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(BusinessValidationError) as excinfo:
        await entry_slip_service.close_absence_and_compose(
            db, 77, resume_date=None, notes=None, actor_id=1
        )
    assert "absence ou un retard" in str(excinfo.value)
    assert record.status is AttendanceStatus.PRESENT


async def test_entry_slip_refused_when_already_excused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux billets sur la même journée feraient croire à deux absences."""
    record = _attendance_record(AttendanceStatus.EXCUSED, date(2026, 5, 18))
    _patch_entry_slip(monkeypatch, record)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(BusinessValidationError):
        await entry_slip_service.close_absence_and_compose(
            db, 77, resume_date=None, notes=None, actor_id=1
        )


async def test_entry_slip_refuses_a_resume_date_before_the_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _attendance_record(AttendanceStatus.ABSENT, date(2026, 5, 18))
    _patch_entry_slip(monkeypatch, record)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(BusinessValidationError) as excinfo:
        await entry_slip_service.close_absence_and_compose(
            db, 77, resume_date=date(2026, 5, 17), notes=None, actor_id=1
        )
    assert "précéder l'absence" in str(excinfo.value)


async def test_entry_slip_closes_the_absence_and_dates_the_resumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le billet bascule l'appel en « excusé » et note pourquoi."""
    record = _attendance_record(AttendanceStatus.ABSENT, date(2026, 5, 18))
    _patch_entry_slip(monkeypatch, record)
    db = SimpleNamespace(commit=AsyncMock())

    data = await entry_slip_service.close_absence_and_compose(
        db, 77, resume_date=date(2026, 5, 20), notes="Certificat médical remis", actor_id=1
    )

    assert record.status is AttendanceStatus.EXCUSED
    assert "billet d'entrée" in record.notes
    assert "Certificat médical remis" in record.notes
    assert data["absence_date"] == date(2026, 5, 18)
    assert data["resume_date"] == date(2026, 5, 20)
    assert data["reference"].startswith("BE-")
    # Pièce interne : aucun sceau numérique n'est émis.
    assert "verification" not in data
    db.commit.assert_awaited_once()


async def test_entry_slip_defaults_the_resumption_to_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans date donnée, l'élève reprend aujourd'hui — le cas du guichet du matin."""
    record = _attendance_record(AttendanceStatus.LATE, date.today())
    _patch_entry_slip(monkeypatch, record)
    db = SimpleNamespace(commit=AsyncMock())

    data = await entry_slip_service.close_absence_and_compose(
        db, 77, resume_date=None, notes=None, actor_id=1
    )
    assert data["resume_date"] == date.today()
    assert isinstance(data["issued_at"], datetime)


# ---------------------------------------------------------------------------
# Permissions — un slug référencé mais jamais installé donne un 403 muet
# ---------------------------------------------------------------------------


_ACT_SLUGS = {
    "documents:school-file-request",
    "documents:entry-slip",
    "documents:parent-summons",
    "documents:zero-cancellation",
}


def test_act_permissions_are_in_the_catalogue() -> None:
    from app.services.tenants.permissions import ALL_PERMISSIONS

    assert _ACT_SLUGS <= {p["slug"] for p in ALL_PERMISSIONS}


def test_every_act_permission_granted_in_a_role_is_also_seeded_by_the_migration() -> None:
    """Le catalogue et la migration doivent accorder exactement les mêmes droits.

    Un établissement déjà ouvert reçoit ses droits par la migration, un
    établissement neuf par le catalogue. Si les deux divergent, la moitié du
    parc voit un bouton qui répond « accès refusé » sans rien expliquer.
    """
    from importlib import util as import_util
    from pathlib import Path

    from app.services.tenants.permissions import ROLE_DEFINITIONS

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260820_0057_school_life_documents.py"
    )
    spec = import_util.spec_from_file_location("migration_0055", path)
    assert spec is not None and spec.loader is not None
    migration = import_util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    seeded = {slug for slug, _ in migration._PERMISSIONS}
    assert seeded == _ACT_SLUGS

    for role, role_def in ROLE_DEFINITIONS.items():
        expected = _ACT_SLUGS & set(role_def["permissions"])
        granted = set(migration._ROLE_GRANTS.get(role, ()))
        assert granted == expected, f"Le rôle « {role} » diverge entre catalogue et migration"
