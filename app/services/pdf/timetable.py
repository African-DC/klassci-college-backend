"""Emploi du temps — PDF landscape A4 grille horaire premium.

La grille jours × heures est spécifique à ce PDF (non applicable au
premium_table générique), mais utilise les CSS variables du theme école
(var(--primary), var(--accent), var(--soft-bg), var(--border)).

Refactor 2026-05-18 : utilise `components.py` (header premium, footer) +
`PDFTheme.from_school` pour les couleurs école dynamiques.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc
from app.services.pdf.theme import PDFTheme

_DAYS_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
_DAYS_FR = {
    "monday": "Lundi",
    "tuesday": "Mardi",
    "wednesday": "Mercredi",
    "thursday": "Jeudi",
    "friday": "Vendredi",
    "saturday": "Samedi",
}

# Palette pastel pour matières (cycle si plus de matières que de couleurs)
_SLOT_COLORS = [
    "#E8F0FE",
    "#FEF3E2",
    "#E8F5E9",
    "#FDE8E8",
    "#EDE7F6",
    "#FFF8E1",
    "#E0F7FA",
    "#FCE4EC",
    "#F3E5F5",
    "#E8EAF6",
]


def _time_to_float(t: str) -> float:
    parts = t.split(":")
    return int(parts[0]) + int(parts[1]) / 60


def _cell_for_hour(
    day_slots: list[dict[str, Any]], hour: int, subject_colors: dict[str, str]
) -> str:
    """HTML d'une cellule de la grille à l'heure donnée (gère les rowspans)."""
    for s in day_slots:
        start = _time_to_float(s["start_time"])
        end = _time_to_float(s["end_time"])
        if abs(start - hour) < 0.01:
            span = max(1, round(end - start))
            bg = subject_colors.get(s.get("subject_name", ""), "#f0f0f0")
            subject = esc(s.get("subject_name", ""))
            teacher = esc(s.get("teacher_name", ""))
            room = esc(s.get("room", ""))
            time_str = f"{s['start_time']}-{s['end_time']}"
            room_div = f'<div style="color:var(--muted);">{room}</div>' if room else ""
            return (
                f'<td rowspan="{span}" style="background:{bg}; vertical-align:top; '
                f"padding:4px; border:1px solid var(--border); font-size:8px; "
                f'line-height:1.3;">'
                f'<div style="font-weight:bold; font-size:9px; color:var(--primary);">'
                f"{subject}</div>"
                f'<div style="color:var(--ink);">{teacher}</div>'
                f"{room_div}"
                f'<div style="color:var(--muted); font-size:7px;">{time_str}</div>'
                f"</td>"
            )
        elif start < hour < end:
            return ""
    return '<td style="border:1px solid var(--border);"></td>'


def generate_timetable_pdf(
    slots: list[dict[str, Any]],
    class_name: str,
    academic_year: str,
    school_settings: dict[str, Any],
    day_start: int = 7,
    day_end: int = 18,
) -> bytes:
    """Generate a landscape A4 timetable PDF — theme école dynamique.

    slots: list of dicts avec day, start_time, end_time, subject_name,
           teacher_name, room, subject_color (optionnel).
    """
    from weasyprint import HTML  # lazy import — voir module docstring

    theme = PDFTheme.from_school(school_settings)

    hours = list(range(day_start, day_end))

    # Couleurs par matière (cycle si pas de couleur explicite)
    subject_colors: dict[str, str] = {}
    color_idx = 0
    for s in slots:
        sname = s.get("subject_name", "")
        if sname and sname not in subject_colors:
            subject_colors[sname] = (
                s.get("subject_color") or _SLOT_COLORS[color_idx % len(_SLOT_COLORS)]
            )
            color_idx += 1

    # Organiser slots par jour + tri intra-jour
    slots_by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in _DAYS_ORDER}
    for s in slots:
        day = s.get("day", "").lower()
        if day in slots_by_day:
            slots_by_day[day].append(s)
    for day in _DAYS_ORDER:
        slots_by_day[day].sort(key=lambda x: x.get("start_time", "00:00"))

    table_rows = ""
    for hour in hours:
        cells = "".join(
            _cell_for_hour(slots_by_day[day], hour, subject_colors) for day in _DAYS_ORDER
        )
        table_rows += f"""
        <tr>
            <td style="background:var(--soft-bg); font-weight:bold; text-align:center;
                       font-size:9px; border:1px solid var(--border); width:50px;
                       color:var(--primary);">
                {hour:02d}:00
            </td>
            {cells}
        </tr>
        """

    day_headers = "".join(
        f'<th style="background:var(--primary); color:white; text-align:center; '
        f'padding:6px; font-size:10px; border:1px solid var(--primary);">'
        f"{_DAYS_FR.get(d, d)}</th>"
        for d in _DAYS_ORDER
    )

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Style additionnel pour la grille (table layout fixe)
    grid_style = """
    <style>
        .pdf-timetable {
            width: 100%; border-collapse: collapse; table-layout: fixed;
            margin-top: 4px;
        }
    </style>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="10mm")}
        {grid_style}
    </head>
    <body>
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="EMPLOI DU TEMPS",
            doc_subtitle=f"{class_name} — {academic_year}",
        )
    }

        <table class="pdf-timetable">
            <thead>
                <tr>
                    <th style="background:var(--primary); color:white; text-align:center;
                                padding:6px; font-size:10px;
                                border:1px solid var(--primary); width:50px;">
                        Heure
                    </th>
                    {day_headers}
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note=f"Imprimé le {now_str}",
        )
    }
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
