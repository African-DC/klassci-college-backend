"""Contrats de la consultation consolidée des échéanciers.

Indépendants du contrat d'une seule inscription : aucun montant de caisse
ne devient accessible par le simple droit de consulter les tranches.
"""

from datetime import date

from pydantic import BaseModel, Field


class ScheduleOverviewRow(BaseModel):
    enrollment_id: int
    student_name: str
    matricule: str | None
    class_id: int
    class_name: str
    source: str
    state: str
    total_due: float
    total_paid: float
    remaining: float
    due_so_far: float
    late_amount: float
    unscheduled_amount: float
    next_due_date: date | None = None
    next_due_amount: float | None = None


class ScheduleOverviewTotals(BaseModel):
    enrollments: int
    late_enrollments: int
    total_due: float
    total_paid: float
    total_remaining: float
    total_late: float


class ScheduleOverviewResponse(BaseModel):
    items: list[ScheduleOverviewRow] = Field(default_factory=list)
    total: int
    page: int
    size: int
    totals: ScheduleOverviewTotals
