"""Tests pour curriculum_service — single source of truth des matières par classe.

Le prédicat `subject_for_class_predicate` est partagé entre le filtre liste
et le validator d'évaluations : ces tests garantissent qu'aucune divergence
ne s'introduit, et que les sémantiques NULL (matières globales / matières
hors-série) restent honorées.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BusinessValidationError, NotFoundError
from app.services.curriculum_service import (
    subject_for_class_predicate,
    subjects_for_class,
    validate_subject_class_pair,
)


def _make_class_stub(level_id: int, series_id: int | None) -> SimpleNamespace:
    """Léger stand-in pour `Class` — le prédicat n'a besoin que de level_id + series_id."""
    return SimpleNamespace(id=99, level_id=level_id, series_id=series_id)


def _mock_scalars_returning(rows: list[object]) -> MagicMock:
    """Construit un faux résultat SQLAlchemy : `result.scalars().all()` retourne `rows`."""
    scalars_proxy = MagicMock()
    scalars_proxy.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars_proxy)
    return result


def _mock_scalar_returning(value: object | None) -> MagicMock:
    """Construit un faux résultat où `result.scalar_one_or_none()` retourne `value`."""
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    return result


# ---------------------------------------------------------------------------
# Predicate — structural correctness
# ---------------------------------------------------------------------------


def test_predicate_compiles_without_error_for_lycee_class() -> None:
    """Une classe de lycée (level + série) produit un prédicat SQL compilable.

    On vérifie que le prédicat se compile en SQL textuel : c'est le contrat
    minimal pour qu'il soit utilisable dans `select(...).where(...)`.
    """
    class_obj = _make_class_stub(level_id=5, series_id=2)
    predicate = subject_for_class_predicate(class_obj)
    rendered = str(predicate.compile(compile_kwargs={"literal_binds": True}))
    # Both null-checks AND equality checks must appear in the rendered SQL.
    assert "subjects.level_id IS NULL" in rendered
    assert "subjects.series_id IS NULL" in rendered
    assert "5" in rendered  # the level_id literal
    assert "2" in rendered  # the series_id literal


def test_predicate_compiles_for_college_class_without_series() -> None:
    """Une classe sans série (collège : 6e, 5e...) compile aussi correctement.

    Le côté Subject du prédicat compare `series_id == None`, qui se rend en
    `IS NULL` côté SQL — la matière globale et celle dont la série est NULL
    matchent toutes deux.
    """
    class_obj = _make_class_stub(level_id=3, series_id=None)
    predicate = subject_for_class_predicate(class_obj)
    rendered = str(predicate.compile(compile_kwargs={"literal_binds": True}))
    assert "subjects.level_id IS NULL" in rendered
    assert "subjects.series_id IS NULL" in rendered


# ---------------------------------------------------------------------------
# subjects_for_class — DB orchestration
# ---------------------------------------------------------------------------


async def test_subjects_for_class_raises_not_found_when_class_missing() -> None:
    """Si la classe n'existe pas, on lève 404 — pas une 200 avec liste vide."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(NotFoundError):
        await subjects_for_class(db, class_id=999)


async def test_subjects_for_class_returns_filtered_rows() -> None:
    """Quand la classe existe, on délègue à db.execute avec le prédicat appliqué."""
    class_obj = _make_class_stub(level_id=5, series_id=2)
    expected_subjects = [
        SimpleNamespace(id=1, name="Mathématiques"),
        SimpleNamespace(id=2, name="Physique-Chimie"),
    ]
    db = AsyncMock()
    db.get = AsyncMock(return_value=class_obj)
    db.execute = AsyncMock(return_value=_mock_scalars_returning(expected_subjects))

    result = await subjects_for_class(db, class_id=99)

    assert result == expected_subjects
    db.get.assert_awaited_once()
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# validate_subject_class_pair — write-side validation
# ---------------------------------------------------------------------------


async def test_validate_pair_passes_when_subject_taught() -> None:
    """Une paire cohérente passe sans exception."""
    class_obj = _make_class_stub(level_id=5, series_id=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=class_obj)
    db.execute = AsyncMock(return_value=_mock_scalar_returning(value=42))

    # Ne lève rien
    await validate_subject_class_pair(db, class_id=99, subject_id=42)


async def test_validate_pair_raises_422_when_subject_not_taught() -> None:
    """Une paire incohérente lève BusinessValidationError (422) avec message FR."""
    class_obj = _make_class_stub(level_id=5, series_id=2)
    db = AsyncMock()
    db.get = AsyncMock(return_value=class_obj)
    db.execute = AsyncMock(return_value=_mock_scalar_returning(value=None))

    with pytest.raises(BusinessValidationError) as exc_info:
        await validate_subject_class_pair(db, class_id=99, subject_id=999)

    # Le message doit être actionnable et en français pour Mme Diallo.
    assert "n'est pas enseignée dans cette classe" in str(exc_info.value.detail)
    assert exc_info.value.status_code == 422


async def test_validate_pair_raises_404_when_class_missing() -> None:
    """Si la classe n'existe pas, on lève 404 avant même de chercher la matière."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    with pytest.raises(NotFoundError):
        await validate_subject_class_pair(db, class_id=12345, subject_id=1)
