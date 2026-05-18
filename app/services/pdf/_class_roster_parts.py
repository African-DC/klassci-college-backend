"""Helpers pour le PDF liste de classe (split de class_roster.py)."""

from __future__ import annotations

from typing import Any

from app.services.pdf._helpers import esc, image_to_datauri


def photo_cell_html(student: dict[str, Any]) -> str:
    """Rendu HTML d'une photo miniature (28×28 circle) ou initiales fallback."""
    photo_url = student.get("photo_url")
    photo_data = image_to_datauri(photo_url) if photo_url else None
    if photo_data:
        return (
            f'<img src="{photo_data}" alt="" style="width:28px; height:28px; '
            f'object-fit:cover; border-radius:50%;" />'
        )
    initials = esc((student.get("initials") or "")[:2])
    return (
        f'<div style="width:28px; height:28px; border-radius:50%; '
        f'background:var(--border); color:var(--muted); display:flex; '
        f'align-items:center; justify-content:center; font-size:9px; '
        f'font-weight:bold;">{initials}</div>'
    )


def student_rows(students: list[dict[str, Any]]) -> list[list[Any]]:
    """Compose les rows premium_table pour la liste de classe.

    Colonnes : N° (num) / Photo (html) / Matricule (muted+mono) /
    Nom Prénoms (html) / Sexe (center) / Né le (muted) / Tél parent.
    """
    rows: list[list[Any]] = []
    for i, s in enumerate(students, 1):
        photo_html = photo_cell_html(s)
        matricule = s.get("enrollment_number") or "—"
        last_name = esc(s.get("last_name", ""))
        first_name = esc(s.get("first_name", ""))
        full_name = f"<strong>{last_name}</strong> {first_name}"
        genre_raw = s.get("genre") or ""
        genre_icon = "M" if genre_raw == "M" else ("F" if genre_raw == "F" else "—")
        birth_date = s.get("birth_date")
        birth_str = birth_date.strftime("%d/%m/%Y") if birth_date else "—"
        parent_phone = s.get("parent_phone") or "—"
        rows.append(
            [
                {"value": str(i), "type": "num"},
                {"value": photo_html, "type": "html"},
                {"value": str(matricule), "type": "muted"},
                {"value": full_name, "type": "html"},
                {"value": genre_icon, "type": "num"},
                {"value": birth_str, "type": "muted"},
                str(parent_phone),
            ]
        )
    return rows


def counter_kpis(counts: dict[str, Any]) -> list[dict[str, Any]]:
    """3 KPI cards : Total / Garçons / Filles."""
    return [
        {
            "label": "Effectif total",
            "value": str(counts.get("total", 0)),
            "tone": "primary",
        },
        {
            "label": "Garçons",
            "value": str(counts.get("boys", 0)),
            "tone": "accent",
        },
        {
            "label": "Filles",
            "value": str(counts.get("girls", 0)),
            "tone": "success",
        },
    ]
