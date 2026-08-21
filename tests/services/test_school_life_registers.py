"""Ce que les deux registres de vie scolaire renvoient, et sur quoi ils comptent.

Trois questions posées ici, toutes venues du guichet :

1. l'éducateur peut-il obtenir les épreuves manquées d'un élève sans lire le
   cahier de notes de sa classe ;
2. un registre qui grossit d'année en année reste-t-il borné ;
3. les quatre compteurs des convocations décrivent-ils l'établissement, ou le
   filtre que l'utilisateur vient de cliquer.
"""

from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import BusinessValidationError
from app.models.grade import GradeStatus
from app.models.school_life import SummonsOutcome
from app.services.school_life import retake_service, summons_service

# ---------------------------------------------------------------------------
# Session simulée — rend les résultats dans l'ordre où le service les demande,
# et conserve chaque requête pour qu'un test puisse dire ce qu'elle filtre.
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def scalars(self) -> _Result:
        return self

    def all(self) -> Any:
        return self._payload

    def scalar_one(self) -> Any:
        return self._payload


class _Session:
    """Session asynchrone de façade : une file de résultats, un journal de SQL."""

    def __init__(self, *results: Any) -> None:
        self._queue = list(results)
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(str(statement))
        return _Result(self._queue.pop(0))


async def _async_none(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _async_empty_dict(*_args: Any, **_kwargs: Any) -> dict[int, str]:
    return {}


def _evaluation(evaluation_id: int, day: date, *, subject: str | None = "Mathématiques") -> Any:
    return SimpleNamespace(
        id=evaluation_id,
        title=f"Devoir n°{evaluation_id}",
        date=day,
        coefficient=2,
        trimester=1,
        subject=SimpleNamespace(name=subject) if subject else None,
    )


def _absent_grade(evaluation: Any) -> Any:
    return SimpleNamespace(
        id=evaluation.id * 10,
        evaluation_id=evaluation.id,
        status=GradeStatus.ABSENT,
        value=None,
        evaluation=evaluation,
    )


# ---------------------------------------------------------------------------
# Épreuves manquées — le croisement que l'écran faisait à la main
# ---------------------------------------------------------------------------


async def test_missed_evaluations_returns_the_reopenable_targets() -> None:
    """Une ligne par épreuve manquée, prête à cocher au guichet."""
    db = _Session(
        [
            _absent_grade(_evaluation(7, date(2026, 5, 18))),
            _absent_grade(_evaluation(8, date(2026, 5, 20), subject=None)),
        ]
    )

    targets = await retake_service.list_missed_evaluations(
        db, student_id=42, period_start=date(2026, 5, 15), period_end=date(2026, 5, 22)
    )

    assert [t.evaluation_id for t in targets] == [7, 8]
    assert targets[0].subject_name == "Mathématiques"
    assert targets[0].date == date(2026, 5, 18)
    assert targets[0].coefficient == 2
    # Une évaluation sans matière rattachée ne fait pas tomber l'écran.
    assert targets[1].subject_name is None


async def test_missed_evaluations_asks_the_database_for_absences_in_the_window() -> None:
    """La sélection se fait en base, pas en mémoire : une requête, pas quarante.

    L'écran interrogeait une fois la classe, puis une fois par évaluation de la
    période. Un trimestre, c'était trente à quarante appels parallèles pour
    afficher deux cases à cocher.
    """
    db = _Session([])

    await retake_service.list_missed_evaluations(
        db, student_id=42, period_start=date(2026, 5, 15), period_end=date(2026, 5, 22)
    )

    assert len(db.statements) == 1
    sql = db.statements[0]
    assert "grades.student_id = " in sql
    assert "grades.status = " in sql
    assert "evaluations.date >= " in sql
    assert "evaluations.date <= " in sql


async def test_missed_evaluations_refuses_a_reversed_window() -> None:
    """Une période à l'envers est une faute de saisie, pas un résultat vide."""
    db = _Session([])
    with pytest.raises(BusinessValidationError) as excinfo:
        await retake_service.list_missed_evaluations(
            db, student_id=42, period_start=date(2026, 5, 22), period_end=date(2026, 5, 15)
        )
    assert "suivre son début" in str(excinfo.value)
    assert db.statements == []


# ---------------------------------------------------------------------------
# Registre des billets — borné
# ---------------------------------------------------------------------------


async def test_retake_register_is_paginated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le registre rend une page, et ce que pèse le registre entier."""
    monkeypatch.setattr(retake_service, "actor_name", _async_none)
    monkeypatch.setattr(retake_service, "current_class_names", _async_empty_dict)
    db = _Session(412, 907, [])

    page = await retake_service.list_authorizations(db, academic_year_id=3, page=2, size=20)

    # Quatre cent douze billets et neuf cent sept épreuves rouvertes sur
    # l'année, pas sur les vingt lignes affichées.
    assert page.total == 412
    assert page.reopened_evaluations == 907
    assert page.page == 2
    assert page.size == 20
    assert page.items == []
    rows_sql = db.statements[2]
    assert "LIMIT" in rows_sql and "OFFSET" in rows_sql
    assert "retake_authorizations.academic_year_id = " in rows_sql


async def test_retake_reopened_count_follows_the_consulted_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le compte d'épreuves rouvertes obéit au trimestre choisi, pas à la page."""
    monkeypatch.setattr(retake_service, "actor_name", _async_none)
    monkeypatch.setattr(retake_service, "current_class_names", _async_empty_dict)
    db = _Session(4, 11, [])

    page = await retake_service.list_authorizations(db, academic_year_id=3, trimester=2)

    assert page.reopened_evaluations == 11
    reopened_sql = db.statements[1]
    assert "retake_authorization_evaluations" in reopened_sql
    assert "retake_authorizations.trimester = " in reopened_sql
    assert "LIMIT" not in reopened_sql


# ---------------------------------------------------------------------------
# Registre des convocations — des compteurs qui ne mentent pas
# ---------------------------------------------------------------------------


def _summons_row(summons_id: int, outcome: SummonsOutcome) -> Any:
    """Convocation telle que le dépôt la rend, relations déjà chargées."""
    return SimpleNamespace(
        id=summons_id,
        student_id=7,
        student=SimpleNamespace(first_name="Aminata", last_name="Traoré", enrollment_number="M1"),
        parent=None,
        parent_id=None,
        parent_name="Mme Traoré",
        academic_year_id=1,
        academic_year=SimpleNamespace(name="2025-2026"),
        trimester=1,
        summons_date=date(2026, 5, 18),
        summons_time=time(10, 0),
        reason="Absences répétées",
        reference=None,
        outcome=outcome,
        outcome_notes=None,
        outcome_recorded_at=None,
        issued_by_user_id=1,
        created_at=datetime(2026, 5, 12, 8, 30),
    )


def _patch_register_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(summons_service, "actor_name", _async_none)
    monkeypatch.setattr(summons_service, "current_class_names", _async_empty_dict)


async def test_summons_counters_ignore_the_outcome_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """« Tuteur absent » filtre la liste, il ne redéfinit pas l'établissement.

    Avant, cliquer sur « Tuteur absent » affichait « Convocations 8, Tuteur
    venu 0, Tuteur absent 8 » : l'éducateur croyait lire un tableau de bord,
    il lisait son propre filtre.
    """
    _patch_register_lookups(monkeypatch)
    db = _Session(
        [(SummonsOutcome.ATTENDED, 12), (SummonsOutcome.MISSED, 8), (SummonsOutcome.PENDING, 5)],
        8,
        [_summons_row(1, SummonsOutcome.MISSED)],
    )

    register = await summons_service.list_register(db, outcome="missed", size=20)

    assert register.summary.total == 25
    assert register.summary.attended == 12
    assert register.summary.missed == 8
    assert register.summary.pending == 5
    # La liste, elle, obéit au filtre.
    assert register.total == 8
    assert [item.outcome for item in register.items] == ["missed"]

    summary_sql, rows_total_sql, rows_sql = db.statements
    assert "parent_summons.outcome = " not in summary_sql
    assert "GROUP BY parent_summons.outcome" in summary_sql
    assert "parent_summons.outcome = " in rows_total_sql
    assert "parent_summons.outcome = " in rows_sql


async def test_summons_counters_survive_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vingt lignes affichées ne font pas vingt convocations dans l'année."""
    _patch_register_lookups(monkeypatch)
    db = _Session(
        [(SummonsOutcome.PENDING, 900)],
        900,
        [_summons_row(i, SummonsOutcome.PENDING) for i in range(20)],
    )

    register = await summons_service.list_register(db, page=1, size=20)

    assert register.summary.total == 900
    assert register.summary.pending == 900
    assert len(register.items) == 20
    assert "LIMIT" in db.statements[2] and "OFFSET" in db.statements[2]


async def test_summons_counters_follow_the_consulted_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L'année et le trimestre disent quel registre on consulte : ils comptent."""
    _patch_register_lookups(monkeypatch)
    db = _Session([(SummonsOutcome.ATTENDED, 4)], 4, [])

    await summons_service.list_register(db, academic_year_id=3, trimester=2)

    summary_sql = db.statements[0]
    assert "parent_summons.academic_year_id = " in summary_sql
    assert "parent_summons.trimester = " in summary_sql


async def test_summons_register_counts_nothing_on_an_empty_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un registre vide affiche quatre zéros, pas quatre tirets ni une erreur."""
    _patch_register_lookups(monkeypatch)
    db = _Session([], 0, [])

    register = await summons_service.list_register(db, academic_year_id=9)

    assert (register.summary.total, register.summary.attended) == (0, 0)
    assert (register.summary.missed, register.summary.pending) == (0, 0)
    assert register.items == []
