"""Emploi du temps — PDF paysage A4, grille horaire premium sur 1 page.

Refonte 2026-07 : la grille est désormais **minute-précise** (positionnement
absolu comme la grille FE `/admin/timetable`), plafonnée à **une seule page**.

- Les créneaux sont placés à la minute près (gère 1h, 1h30, 2h, un début à
  10h30, etc.) au lieu de l'ancien `rowspan = round(fin - début)` qui écrasait
  ou perdait tout créneau non aligné sur l'heure.
- La plage horaire est **rognée aux heures réellement utilisées** (min début →
  max fin) : plus de bandes vides de 7h à 18h qui poussaient sur une 2e page.
- La hauteur de la grille est **calculée pour tenir sur une page** paysage A4.
- Les couleurs de matière sont des **pastels « ciel »** (fond clair Tailwind-100
  + texte foncé -800) : lisibles, jamais un aplat sombre qui masque le texte.

Utilise `components.py` (header/footer premium) + `PDFTheme.from_school` pour
les couleurs école dynamiques (var(--primary), var(--accent), etc.).
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

# Jetons de couleur « ciel » : fond pastel (Tailwind-100), bordure (-300),
# texte foncé (-800). Miroir du COLOR_MAP de la grille FE — garantit un texte
# toujours lisible (contraste fond clair / texte foncé), jamais un aplat sombre.
_COLOR_TOKENS: dict[str, tuple[str, str, str]] = {
    "blue": ("#dbeafe", "#93c5fd", "#1e40af"),
    "cyan": ("#cffafe", "#67e8f9", "#155e75"),
    "teal": ("#ccfbf1", "#5eead4", "#115e59"),
    "indigo": ("#e0e7ff", "#a5b4fc", "#3730a3"),
    "violet": ("#ede9fe", "#c4b5fd", "#5b21b6"),
    "emerald": ("#d1fae5", "#6ee7b7", "#065f46"),
    "green": ("#dcfce7", "#86efac", "#166534"),
    "amber": ("#fef3c7", "#fcd34d", "#92400e"),
    "orange": ("#ffedd5", "#fdba74", "#9a3412"),
    "rose": ("#ffe4e6", "#fda4af", "#9f1239"),
    "pink": ("#fce7f3", "#f9a8d4", "#9d174d"),
    "red": ("#fee2e2", "#fca5a5", "#991b1b"),
}
# Ordre de repli (le plus « ciel » d'abord) pour les matières sans couleur.
_FALLBACK_CYCLE = [
    "blue",
    "cyan",
    "teal",
    "indigo",
    "violet",
    "emerald",
    "amber",
    "orange",
    "rose",
    "pink",
    "green",
    "red",
]
_NEUTRAL_TOKEN = ("#eef2f6", "#cbd5e1", "#334155")

# --- Contraintes de mise en page (paysage A4, tenir sur 1 page) ---------------
# Espace vertical disponible pour la grille après en-tête + ligne des jours +
# légende + pied de page (en px CSS ; ~475px sur A4 paysage marge 8mm).
_GRID_AVAIL_PX = 430.0
_HOUR_H_MAX = 56.0  # cellule pas démesurée pour une journée courte
_HOUR_H_MIN = 26.0  # plancher de lisibilité (journées très longues)
_GUTTER_PCT = 7.0  # largeur de la colonne des heures (%)
_DAYHEAD_H = 26.0  # hauteur de la ligne des jours (px)


def _time_to_min(t: str) -> int:
    """'08:30' -> 510 minutes."""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _fmt_min(m: int) -> str:
    """510 -> '08:30'."""
    return f"{m // 60:02d}:{m % 60:02d}"


def _resolve_color(
    token: str | None, cache: dict[str, tuple[str, str, str]], name: str
) -> tuple[str, str, str]:
    """Résout un jeton de couleur matière en (fond, bordure, texte) pastel."""
    if name in cache:
        return cache[name]
    key = (token or "").strip().lower()
    if key in _COLOR_TOKENS:
        resolved = _COLOR_TOKENS[key]
    elif name:
        resolved = _COLOR_TOKENS[_FALLBACK_CYCLE[len(cache) % len(_FALLBACK_CYCLE)]]
    else:
        resolved = _NEUTRAL_TOKEN
    cache[name] = resolved
    return resolved


def _slot_html(
    slot: dict[str, Any],
    *,
    left_pct: float,
    width_pct: float,
    top_px: float,
    height_px: float,
    colors: tuple[str, str, str],
) -> str:
    """Bloc d'un créneau positionné à la minute près."""
    bg, border, text = colors
    subject = esc(slot.get("subject_name", ""))
    teacher = esc(slot.get("teacher_name", ""))
    room = esc(slot.get("room") or "")
    time_str = f"{slot['start_time']}–{slot['end_time']}"

    # Divulgation progressive selon la hauteur (comme la grille FE).
    lines = [f'<div class="tt-slot-subject">{subject}</div>']
    if height_px >= 30 and teacher:
        lines.append(f'<div class="tt-slot-sub">{teacher}</div>')
    if height_px >= 44 and room:
        lines.append(f'<div class="tt-slot-sub tt-slot-room">{room}</div>')
    if height_px >= 58:
        lines.append(f'<div class="tt-slot-time">{time_str}</div>')

    style = (
        f"left:{left_pct:.3f}%; width:{width_pct:.3f}%; "
        f"top:{top_px:.1f}px; height:{height_px:.1f}px; "
        f"background:{bg}; border-color:{border}; color:{text};"
    )
    return f'<div class="tt-slot" style="{style}">{"".join(lines)}</div>'


def generate_timetable_pdf(
    slots: list[dict[str, Any]],
    class_name: str,
    academic_year: str,
    school_settings: dict[str, Any],
    day_start: int = 7,
    day_end: int = 18,
) -> bytes:
    """Génère l'emploi du temps en PDF paysage A4, sur une seule page.

    slots : dicts avec day, start_time, end_time, subject_name, teacher_name,
            room, subject_color (jeton nommé optionnel : 'blue', 'rose', ...).
    """
    from weasyprint import HTML  # lazy import — WeasyPrint charge GTK au 1er appel

    theme = PDFTheme.from_school(school_settings)
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Organiser + trier les créneaux par jour.
    slots_by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in _DAYS_ORDER}
    for s in slots:
        day = (s.get("day") or "").lower()
        if day in slots_by_day:
            slots_by_day[day].append(s)
    for day in _DAYS_ORDER:
        slots_by_day[day].sort(key=lambda x: x.get("start_time", "00:00"))

    # La semaine de classe entiere, du lundi au vendredi, meme si un jour est
    # vide. Ne montrer que les jours remplis faisait disparaitre le vendredi
    # d'un emploi du temps incomplet : on lisait « pas de cours ce jour-la »
    # la ou il fallait lire « creneaux pas encore poses ».
    # Le samedi ne s'ajoute que s'il porte un cours : toutes les ecoles n'en
    # font pas, et une colonne vide de plus mangerait la largeur des autres.
    active_days = [*_DAYS_ORDER[:5]]
    if slots_by_day.get("saturday"):
        active_days.append("saturday")

    # Couleurs par matière (résolues une fois, réutilisées grille + légende).
    color_cache: dict[str, tuple[str, str, str]] = {}
    subject_order: list[str] = []
    for d in active_days:
        for s in slots_by_day[d]:
            sname = s.get("subject_name") or ""
            if sname and sname not in color_cache:
                _resolve_color(s.get("subject_color"), color_cache, sname)
                subject_order.append(sname)

    # Bornes horaires : rognées aux heures réellement utilisées (arrondi à l'heure).
    all_starts = [_time_to_min(s["start_time"]) for s in slots if s.get("start_time")]
    all_ends = [_time_to_min(s["end_time"]) for s in slots if s.get("end_time")]
    if all_starts and all_ends:
        grid_start = (min(all_starts) // 60) * 60
        grid_end = -(-max(all_ends) // 60) * 60  # ceil vers l'heure
    else:
        grid_start = day_start * 60
        grid_end = day_end * 60
    span_min = max(60, grid_end - grid_start)
    span_hours = span_min / 60.0

    # Hauteur d'heure calée pour tenir sur une page.
    hour_h = min(_HOUR_H_MAX, max(_HOUR_H_MIN, _GRID_AVAIL_PX / span_hours))
    grid_h = span_min / 60.0 * hour_h
    px_per_min = hour_h / 60.0

    n_days = len(active_days)
    day_w = (100.0 - _GUTTER_PCT) / n_days

    def _top(minute: int) -> float:
        return (minute - grid_start) * px_per_min

    def _label_top(minute: int) -> float:
        # Garde le libellé entièrement visible aux deux extrémités de la grille.
        return min(max(0.0, _top(minute) - 5.0), max(0.0, grid_h - 9.0))

    # --- Lignes horaires + bandes zébrées + libellés d'heure -------------------
    hour_marks = list(range(grid_start, grid_end + 1, 60))
    grid_layers: list[str] = []
    # Bandes zébrées (heures paires) pour scanner à l'horizontale.
    for i, m in enumerate(hour_marks[:-1]):
        if i % 2 == 1:
            grid_layers.append(
                f'<div class="tt-band" style="top:{_top(m):.1f}px; height:{hour_h:.1f}px;"></div>'
            )
    # Lignes horaires pleines + libellé dans la gouttière.
    for m in hour_marks:
        grid_layers.append(f'<div class="tt-hline" style="top:{_top(m):.1f}px;"></div>')
        grid_layers.append(
            f'<div class="tt-hlabel" style="top:{_label_top(m):.1f}px; '
            f'width:{_GUTTER_PCT:.2f}%;">{_fmt_min(m)}</div>'
        )
    # Demi-heures (pointillé léger).
    for m in range(grid_start + 30, grid_end, 60):
        grid_layers.append(
            f'<div class="tt-hline tt-hline-half" style="top:{_top(m):.1f}px;"></div>'
        )

    # Libellés d'horaires « spéciaux » (débuts/fins non alignés sur l'heure).
    # Libellés d'horaires non alignés sur l'heure (l'heure exacte figure aussi
    # dans le créneau). On saute ceux à moins de 5 min d'une heure pleine pour
    # éviter qu'ils ne chevauchent le libellé d'heure (ex. 08:02 vs 08:00).
    special: set[int] = set()
    for s in slots:
        for key in ("start_time", "end_time"):
            if s.get(key):
                mm = _time_to_min(s[key])
                offset = mm % 60
                if offset != 0 and min(offset, 60 - offset) >= 5 and grid_start <= mm <= grid_end:
                    special.add(mm)
    for mm in sorted(special):
        grid_layers.append(
            f'<div class="tt-hlabel tt-hlabel-soft" style="top:{_label_top(mm):.1f}px; '
            f'width:{_GUTTER_PCT:.2f}%;">{_fmt_min(mm)}</div>'
        )

    # Séparateurs verticaux de colonnes (gouttière + entre jours).
    for i in range(n_days + 1):
        left = _GUTTER_PCT + i * day_w
        grid_layers.append(f'<div class="tt-vline" style="left:{left:.3f}%;"></div>')

    # --- Créneaux --------------------------------------------------------------
    for di, day in enumerate(active_days):
        left = _GUTTER_PCT + di * day_w
        for s in slots_by_day[day]:
            start = _time_to_min(s["start_time"])
            end = _time_to_min(s["end_time"])
            top = _top(start)
            height = max(14.0, (end - start) * px_per_min)
            colors = color_cache.get(s.get("subject_name") or "", _NEUTRAL_TOKEN)
            grid_layers.append(
                _slot_html(
                    s,
                    left_pct=left + 0.4,
                    width_pct=day_w - 0.8,
                    top_px=top + 0.6,
                    height_px=height - 1.2,
                    colors=colors,
                )
            )

    # En-tête des jours : positionné en absolu sur EXACTEMENT le même système de
    # pourcentages que les colonnes de la grille → alignement parfait (pas de
    # dérive due au modèle de boîte du flex).
    day_headers = "".join(
        f'<div class="tt-dayhead{" tt-dayhead-last" if i == n_days - 1 else ""}" '
        f'style="left:{_GUTTER_PCT + i * day_w:.3f}%; width:{day_w:.3f}%;">'
        f"{_DAYS_FR.get(d, d)}</div>"
        for i, d in enumerate(active_days)
    )

    # Légende matière → couleur (décode les pastels, remplit le bas de page).
    legend_chips = ""
    for sname in subject_order:
        bg, border, _text = color_cache[sname]
        legend_chips += (
            f'<span class="tt-legend-chip">'
            f'<span class="tt-legend-swatch" style="background:{bg}; border-color:{border};"></span>'
            f"{esc(sname)}</span>"
        )
    legend_html = f'<div class="tt-legend">{legend_chips}</div>' if legend_chips else ""

    has_slots = any(slots_by_day[d] for d in active_days)
    if has_slots:
        grid_block = f"""
        <div class="tt-wrap">
            <div class="tt-head">{day_headers}</div>
            <div class="tt-grid" style="height:{grid_h:.1f}px;">
                {"".join(grid_layers)}
            </div>
        </div>
        {legend_html}
        """
    else:
        grid_block = '<div class="tt-empty">Aucun cours programmé pour cette classe.</div>'

    grid_style = f"""
    <style>
        .tt-wrap {{ margin-top: 6px; }}
        .tt-head {{ position: relative; height: {_DAYHEAD_H:.0f}px; margin-bottom: 2px; }}
        .tt-dayhead {{
            position: absolute; top: 0; bottom: 0; box-sizing: border-box;
            display: flex; align-items: center; justify-content: center;
            padding: 0 2px; text-align: center;
            background: var(--primary); color: #fff; font-size: 9.5px;
            font-weight: 700; letter-spacing: 0.4px;
            border-right: 1px solid rgba(255,255,255,0.4);
            border-radius: 4px 4px 0 0; overflow: hidden;
        }}
        .tt-dayhead-last {{ border-right: none; }}
        .tt-grid {{
            position: relative; width: 100%;
            border: 0.75px solid var(--border); border-top: none;
            border-radius: 0 0 5px 5px; overflow: hidden;
        }}
        .tt-band {{
            position: absolute; left: {_GUTTER_PCT:.2f}%; right: 0;
            background: var(--soft-bg); opacity: 0.55;
        }}
        .tt-hline {{
            position: absolute; left: {_GUTTER_PCT:.2f}%; right: 0; height: 0;
            border-top: 0.75px solid var(--border);
        }}
        .tt-hline-half {{ border-top: 0.5px dashed var(--border); opacity: 0.5; }}
        .tt-vline {{
            position: absolute; top: 0; bottom: 0; width: 0;
            border-left: 0.75px solid var(--border);
        }}
        .tt-hlabel {{
            position: absolute; left: 0; text-align: right; padding-right: 6px;
            font-size: 8px; font-weight: 600; color: var(--primary);
            font-variant-numeric: tabular-nums;
        }}
        .tt-hlabel-soft {{ font-size: 7px; font-weight: 500; color: var(--muted); }}
        .tt-slot {{
            position: absolute; border: 0.75px solid; border-radius: 4px;
            padding: 2.5px 4px; overflow: hidden; box-sizing: border-box;
            line-height: 1.15;
        }}
        .tt-slot-subject {{ font-weight: 700; font-size: 8.5px; }}
        .tt-slot-sub {{ font-size: 7.2px; color: #3f3f46; margin-top: 1px; }}
        .tt-slot-room {{ color: #52525b; }}
        .tt-slot-time {{
            font-size: 6.6px; color: #52525b; margin-top: 1px;
            font-variant-numeric: tabular-nums;
        }}
        /* Légende : conteneur flex (le `gap` n'étant pas honoré par WeasyPrint,
           l'espacement passe par les marges des puces). */
        .tt-legend {{
            display: flex; flex-wrap: wrap; align-items: center;
            margin-top: 8px; padding-top: 7px;
            border-top: 0.75px solid var(--border);
        }}
        .tt-legend-chip {{
            display: inline-flex; align-items: center;
            margin: 0 15px 3px 0; font-size: 8px; color: var(--ink);
        }}
        .tt-legend-swatch {{
            width: 11px; height: 11px; border-radius: 3px; border: 0.75px solid;
            display: inline-block; margin-right: 6px;
        }}
        .tt-empty {{
            padding: 30px; text-align: center; color: var(--muted); font-size: 11px;
        }}
    </style>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4 landscape", margin="8mm 10mm")}
        {grid_style}
    </head>
    <body>
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type="EMPLOI DU TEMPS",
            doc_subtitle=f"{class_name} — {academic_year}",
        )
    }
        {grid_block}
        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            note=f"Imprimé le {now_str}",
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
