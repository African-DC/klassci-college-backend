"""Schemas Pydantic — score de performance enseignant + activité personnel.

Deux vues distinctes, volontairement asymétriques :

- **Enseignants** : un score /100 *transparent* décomposé en 3 axes (assiduité,
  saisie des notes, prise de l'appel). Chaque axe porte son propre sous-score
  ET un flag `sufficient` : si KLASSCI n'a pas encore assez de données pour un
  axe, on ne fabrique pas un chiffre trompeur, on le marque « données
  insuffisantes ». Le score global n'agrège que les axes suffisamment nourris.

- **Personnel** : PAS de score /100 fabriqué (les données disponibles —
  paiements encaissés, inscriptions traitées — ne mesurent pas une
  « performance » comparable). On expose un tableau d'activité factuel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Enseignants — score par axe + global
# ---------------------------------------------------------------------------


class PerformanceAxis(BaseModel):
    """Un axe du score enseignant (assiduité / notes / appel).

    `score` est None quand `sufficient` est False : l'axe manque de données
    (aucune session pointée, aucune évaluation, aucun créneau planifié…).
    `detail` porte les compteurs bruts pour justifier le score dans l'UI.
    """

    key: str  # "assiduite" | "notes" | "appel"
    label: str
    weight: float  # part de l'axe dans le global (0..1)
    score: float | None  # 0..100
    sufficient: bool
    detail: dict[str, Any]


class TeacherPerformanceItem(BaseModel):
    teacher_id: int
    user_id: int | None
    first_name: str
    last_name: str
    speciality: str | None
    photo_url: str | None
    global_score: float | None  # 0..100, None si aucun axe suffisant
    rating: str  # "excellent" | "bon" | "a_ameliorer" | "insuffisant_donnees"
    sufficient: bool
    axes: list[PerformanceAxis]


class PerformanceSummary(BaseModel):
    """KPIs d'en-tête pour la page admin."""

    teachers_total: int
    teachers_scored: int  # avec au moins un axe suffisant
    teachers_insufficient: int
    teachers_avg_score: float | None  # moyenne des scorés
    staff_total: int
    staff_active: int  # personnel avec au moins une action sur l'année


class TeacherPerformanceListResponse(BaseModel):
    academic_year_id: int
    academic_year_name: str
    teachers: list[TeacherPerformanceItem]
    summary: PerformanceSummary


class TeacherSelfPerformanceResponse(BaseModel):
    """Vue « Ma performance » de l'enseignant connecté."""

    academic_year_id: int
    academic_year_name: str
    performance: TeacherPerformanceItem


# ---------------------------------------------------------------------------
# Personnel — activité factuelle (pas de score /100)
# ---------------------------------------------------------------------------


class StaffActivityItem(BaseModel):
    user_id: int
    first_name: str
    last_name: str
    position: str | None
    photo_url: str | None
    payments_count: int
    payments_amount: float
    enrollments_count: int
    last_login: datetime | None


class StaffActivityListResponse(BaseModel):
    academic_year_id: int
    academic_year_name: str
    staff: list[StaffActivityItem]
