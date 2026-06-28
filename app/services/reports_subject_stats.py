"""Statistiques de classe pour l'enrichissement du bulletin.

Fonctions pures (aucune I/O) : on leur passe les bulletins d'une classe pour un
trimestre, elles calculent par matière la moyenne/min/max de la classe et le
rang de chaque élève, ainsi que les statistiques générales de la classe.

Séparé de `reports_service` pour respecter `no-god-code.md` (reports_service
proche de 500 LOC).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _rank_pairs(pairs: list[tuple[int, Decimal]]) -> dict[int, int]:
    """Rang par compétition (ex-aequo partagent le rang), moyenne décroissante."""
    ranked = sorted(pairs, key=lambda x: x[1], reverse=True)
    ranks: dict[int, int] = {}
    for i, (student_id, avg) in enumerate(ranked):
        if i > 0 and avg == ranked[i - 1][1]:
            ranks[student_id] = ranks[ranked[i - 1][0]]
        else:
            ranks[student_id] = i + 1
    return ranks


def compute_subject_stats(class_bulletins: list[Any]) -> dict[int, dict[str, Any]]:
    """Par subject_id : {avg, min, max, count, ranks: {student_id: rang}}.

    `class_bulletins` : bulletins de la classe pour un trimestre, chacun avec
    `subject_averages` chargé (chaque sa porte subject_id, student_id, average).
    """
    by_subject: dict[int, list[tuple[int, Decimal]]] = defaultdict(list)
    for bulletin in class_bulletins:
        student_id = bulletin.student_id
        for sa in bulletin.subject_averages or []:
            if sa.average is not None:
                by_subject[sa.subject_id].append((student_id, sa.average))

    stats: dict[int, dict[str, Any]] = {}
    for subject_id, pairs in by_subject.items():
        values = [avg for _, avg in pairs]
        stats[subject_id] = {
            "avg": _quantize(sum(values) / len(values)),
            "min": min(values),
            "max": max(values),
            "count": len(values),
            "ranks": _rank_pairs(pairs),
        }
    return stats


def enrich_subject_rows(
    bulletin: Any, subject_stats: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Lignes matières du bulletin enrichies du prof, du rang et de la moy. classe."""
    rows: list[dict[str, Any]] = []
    for sa in bulletin.subject_averages or []:
        stats = subject_stats.get(sa.subject_id, {})
        teacher = getattr(sa.subject, "teacher", None) if sa.subject else None
        teacher_name = f"{teacher.first_name} {teacher.last_name}".strip() if teacher else None
        rows.append(
            {
                "subject_name": sa.subject.name if sa.subject else "",
                "average": sa.average,
                "coefficient": sa.coefficient,
                "teacher_name": teacher_name,
                "rank": stats.get("ranks", {}).get(bulletin.student_id),
                "class_avg": stats.get("avg"),
                "class_count": stats.get("count"),
            }
        )
    return rows


def compute_general_stats(class_bulletins: list[Any]) -> dict[str, Any]:
    """Statistiques de la moyenne générale sur la classe (depuis bulletin.average)."""
    values = [b.average for b in class_bulletins if b.average is not None]
    if not values:
        return {"class_avg": None, "class_min": None, "class_max": None, "count": 0}
    return {
        "class_avg": _quantize(sum(values) / len(values)),
        "class_min": min(values),
        "class_max": max(values),
        "count": len(values),
    }
