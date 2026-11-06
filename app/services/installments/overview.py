"""Point consolidé des échéanciers, dérivé des calculs individuels.

Pas de seconde mécanique d'allocation ou de retard : on réutilise
`resolve_grid_amounts` et `compute_arrears`, avec les totaux groupés de
la même source SQL que `resolve_schedule`. Le résultat filtré sert aussi
bien à l'écran qu'aux exports PDF et Excel.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import installment_overview_repository as repo
from app.repositories import installment_repository
from app.schemas.installment_overview import (
    ScheduleOverviewResponse,
    ScheduleOverviewRow,
    ScheduleOverviewTotals,
)
from app.services.installments._math import compute_arrears, resolve_grid_amounts
from app.services.installments.schedule import _to_grid_line

OverviewState = Literal[
    "all",
    "late",
    "on_track",
    "settled",
    "unconfigured",
    "partial_schedule",
    "no_fees",
]
_ZERO = Decimal("0")


def _status(
    *,
    source: str,
    due: Decimal,
    paid: Decimal,
    late: Decimal,
    unscheduled: Decimal,
) -> str:
    """Un seul statut primaire ; les montants restent disponibles séparément."""
    if due <= _ZERO:
        return "no_fees"
    if late > _ZERO:
        return "late"
    if source == "none":
        return "unconfigured"
    if unscheduled > _ZERO:
        return "partial_schedule"
    if paid >= due:
        return "settled"
    return "on_track"


async def overview(
    db: AsyncSession,
    *,
    academic_year_id: int,
    class_id: int | None = None,
    search: str = "",
    state: OverviewState = "all",
    page: int = 1,
    size: int = 20,
) -> ScheduleOverviewResponse:
    """Situation en temps réel, toutes caisses confondues, avec filtres serveur.

    Le même ensemble de lignes et les mêmes totaux sont utilisés par les
    exports ; une page de 20 résultats n'exporte jamais seulement ces 20 lignes.
    Les 5 000 inscriptions maxi sont gardées par le repository, avec erreur
    explicite au-delà — pas d'export silencieusement incomplet.
    """
    identities = await repo.list_identities(
        db, academic_year_id=academic_year_id, class_id=class_id, search=search
    )
    ids = [x.enrollment_id for x in identities]
    due_by_id = await repo.mandatory_totals(db, ids)
    paid_by_id = await repo.mandatory_paid(db, ids)
    negotiated_by_id = await repo.negotiated_plans(db, ids)
    grid = await installment_repository.list_year_grid(db, academic_year_id)
    grid_lines = [_to_grid_line(item) for item in grid]
    today = date_type.today()

    rows: list[ScheduleOverviewRow] = []
    for enrollment in identities:
        eid = enrollment.enrollment_id
        due = due_by_id.get(eid, _ZERO)
        paid = paid_by_id.get(eid, _ZERO)
        negotiated = negotiated_by_id.get(eid, [])
        if negotiated:
            source = "negotiated"
            plan = [(part.due_date, Decimal(str(part.amount))) for part in negotiated]
        elif grid:
            source = "standard"
            parts = resolve_grid_amounts(due, grid_lines)
            plan = [
                (part.due_date, amount) for part, amount in zip(grid, parts, strict=True)
            ]
        else:
            source = "none"
            plan = []

        # Le calcul pur suppose l'ordre chronologique, pas un ordre arbitraire
        # d'ID ou de saisie.
        plan.sort(key=lambda pair: pair[0])
        arrears = compute_arrears(plan, paid, today)
        planned = sum((amount for _due_date, amount in plan), _ZERO)
        unscheduled = max(_ZERO, due - planned)
        row_state = _status(
            source=source,
            due=due,
            paid=paid,
            late=arrears.late_amount,
            unscheduled=unscheduled,
        )

        if state != "all" and row_state != state:
            continue
        rows.append(
            ScheduleOverviewRow(
                enrollment_id=eid,
                student_name=f"{enrollment.last_name} {enrollment.first_name}".strip(),
                matricule=enrollment.matricule,
                class_id=enrollment.class_id,
                class_name=enrollment.class_name,
                source=source,
                state=row_state,
                total_due=float(due),
                total_paid=float(paid),
                remaining=float(max(_ZERO, due - paid)),
                due_so_far=float(arrears.due_so_far),
                late_amount=float(arrears.late_amount),
                unscheduled_amount=float(unscheduled),
                next_due_date=arrears.next_due_date,
                next_due_amount=(
                    float(arrears.next_due_amount)
                    if arrears.next_due_amount is not None else None
                ),
            )
        )

    # Les compteurs portent sur l'ensemble filtré, et non uniquement sur les
    # vingt lignes visibles. Une somme de valeurs arrondies est sûre ici :
    # le FCFA est un franc entier dans le moteur de répartition.
    totals = ScheduleOverviewTotals(
        enrollments=len(rows),
        late_enrollments=sum(r.late_amount > 0 for r in rows),
        total_due=sum(r.total_due for r in rows),
        total_paid=sum(r.total_paid for r in rows),
        total_remaining=sum(r.remaining for r in rows),
        total_late=sum(r.late_amount for r in rows),
    )
    start = (page - 1) * size
    return ScheduleOverviewResponse(
        items=rows[start : start + size],
        total=len(rows),
        page=page,
        size=size,
        totals=totals,
    )
