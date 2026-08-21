"""Tranches de paiement — grille d'établissement et accords négociés.

| Module     | Rôle |
|------------|------|
| `_math`    | chiffrage d'une grille mixte et calcul du retard (pur, testé seul) |
| `schedule` | résolution de l'échéancier applicable à une inscription |
| `grid`     | écriture de la grille d'année et des accords par famille |
"""

from app.services.installments._math import (
    Arrears,
    GridLine,
    compute_arrears,
    resolve_grid_amounts,
    split_by_percentage,
)
from app.services.installments.grid import (
    clear_enrollment_plan,
    list_grid,
    replace_grid,
    set_enrollment_plan,
)
from app.services.installments.schedule import resolve_schedule

__all__ = [
    "Arrears",
    "GridLine",
    "clear_enrollment_plan",
    "compute_arrears",
    "list_grid",
    "replace_grid",
    "resolve_grid_amounts",
    "resolve_schedule",
    "set_enrollment_plan",
    "split_by_percentage",
]
