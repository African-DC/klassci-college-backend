"""Helpers pour le PDF PV conseil de classe (split de council_minutes.py)."""

from __future__ import annotations

from typing import Any

from app.services.pdf._helpers import format_decimal


def count_decisions(decisions: list[dict[str, Any]], target: str) -> int:
    """Compte les décisions finales (ou auto à défaut) correspondant à `target`."""
    return sum(
        1
        for d in decisions
        if (d.get("final_decision") or d.get("auto_decision")) == target
    )


def decision_rows(decisions: list[dict[str, Any]]) -> list[list[Any]]:
    """Compose les rows premium_table pour les décisions du conseil.

    Colonnes : N° / Élève / Moyenne (num) / Rang (num) / Absences (num) /
    Décision auto / Décision finale (pill) / Motif modification (muted).
    """
    rows: list[list[Any]] = []
    for i, d in enumerate(decisions, 1):
        final = d.get("final_decision") or d.get("auto_decision", "") or ""
        avg = d.get("average")
        avg_str = format_decimal(avg) if avg is not None else "—"
        rank = d.get("rank")
        rank_str = str(rank) if rank else "—"
        absences = d.get("absence_count", 0) or 0
        rows.append(
            [
                {"value": str(i), "type": "num"},
                d.get("student_name", ""),
                {"value": avg_str, "type": "num"},
                {"value": rank_str, "type": "num"},
                {"value": str(absences), "type": "num"},
                d.get("auto_decision", "") or "—",
                {"value": str(final).lower(), "type": "pill", "label": str(final).title() or "—"},
                {"value": d.get("override_reason", "") or "", "type": "muted"},
            ]
        )
    return rows


def recap_kpis(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """4 KPI cards : Passages / Repêchages / Redoublements / Exclusions."""
    return [
        {
            "label": "Passages",
            "value": str(count_decisions(decisions, "passage")),
            "tone": "success",
        },
        {
            "label": "Repêchages",
            "value": str(count_decisions(decisions, "repechage")),
            "tone": "warn",
        },
        {
            "label": "Redoublements",
            "value": str(count_decisions(decisions, "redoublement")),
            "tone": "warn",
        },
        {
            "label": "Exclusions",
            "value": str(count_decisions(decisions, "exclusion")),
            "tone": "primary",
        },
    ]
