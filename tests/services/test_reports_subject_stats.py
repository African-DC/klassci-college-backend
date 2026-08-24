"""Tests pour reports_subject_stats — stats de classe du bulletin (fonctions pures).

Garantit le rang par compétition (ex-aequo partagés), les min/max/moyenne par
matière, les stats générales de classe, et l'enrichissement des lignes matière
(prof, rang, moyenne de classe).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.services.reports_subject_stats import (
    compute_general_stats,
    compute_subject_stats,
    enrich_subject_rows,
)


def _sa(subject_id: int, average, *, subject=None, coefficient: int = 1):
    return SimpleNamespace(
        subject_id=subject_id,
        average=Decimal(str(average)) if average is not None else None,
        coefficient=coefficient,
        subject=subject,
    )


def _bulletin(student_id: int, averages, *, average=None):
    return SimpleNamespace(
        student_id=student_id,
        subject_averages=averages,
        average=Decimal(str(average)) if average is not None else None,
    )


def test_subject_stats_avg_min_max():
    bulletins = [
        _bulletin(1, [_sa(10, 10)]),
        _bulletin(2, [_sa(10, 20)]),
        _bulletin(3, [_sa(10, 15)]),
    ]
    stats = compute_subject_stats(bulletins)
    assert stats[10]["avg"] == Decimal("15.00")
    assert stats[10]["min"] == Decimal("10")
    assert stats[10]["max"] == Decimal("20")
    assert stats[10]["count"] == 3


def test_subject_rank_competition_with_ties():
    bulletins = [
        _bulletin(1, [_sa(10, 18)]),  # rang 1
        _bulletin(2, [_sa(10, 18)]),  # rang 1 (ex-aequo)
        _bulletin(3, [_sa(10, 12)]),  # rang 3 (saut après ex-aequo)
    ]
    ranks = compute_subject_stats(bulletins)[10]["ranks"]
    assert ranks == {1: 1, 2: 1, 3: 3}


def test_subject_stats_ignores_none_averages():
    bulletins = [_bulletin(1, [_sa(10, None)]), _bulletin(2, [_sa(10, 14)])]
    stats = compute_subject_stats(bulletins)
    assert stats[10]["count"] == 1
    assert stats[10]["avg"] == Decimal("14.00")


def test_general_stats():
    bulletins = [
        _bulletin(1, [], average=10),
        _bulletin(2, [], average=14),
        _bulletin(3, [], average=None),
    ]
    g = compute_general_stats(bulletins)
    assert g["class_avg"] == Decimal("12.00")
    assert g["class_min"] == Decimal("10")
    assert g["class_max"] == Decimal("14")
    assert g["count"] == 2


def test_general_stats_empty():
    assert compute_general_stats([])["class_avg"] is None


def test_enrich_rows_carries_teacher_rank_and_class_avg():
    teacher = SimpleNamespace(first_name="Jean", last_name="Kouassi")
    subject = SimpleNamespace(name="Mathématiques", teacher=teacher)
    bulletin = _bulletin(7, [_sa(10, 16, subject=subject, coefficient=4)])
    stats = {10: {"avg": Decimal("12.50"), "ranks": {7: 2}}}
    rows = enrich_subject_rows(bulletin, stats)
    assert rows[0]["subject_name"] == "Mathématiques"
    assert rows[0]["teacher_name"] == "Jean Kouassi"
    assert rows[0]["rank"] == 2
    assert rows[0]["class_avg"] == Decimal("12.50")
    assert rows[0]["coefficient"] == 4
