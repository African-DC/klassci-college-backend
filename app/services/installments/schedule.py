"""Résolution de l'échéancier d'une inscription et de son état de retard."""

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enrollment import Enrollment
from app.repositories import installment_repository as repo
from app.schemas.installment import EnrollmentScheduleResponse, ScheduleLine
from app.services.installments._math import compute_arrears, split_by_percentage

# Trois provenances possibles pour un échéancier, dans cet ordre de priorité.
SOURCE_NEGOTIATED = "negotiated"
SOURCE_STANDARD = "standard"
SOURCE_NONE = "none"


async def _academic_year_id(db: AsyncSession, enrollment_id: int) -> int:
    stmt = select(Enrollment.academic_year_id).where(Enrollment.id == enrollment_id)
    year_id = (await db.execute(stmt)).scalar_one_or_none()
    if year_id is None:
        raise NotFoundError("Enrollment", enrollment_id)
    return int(year_id)


async def resolve_schedule(
    db: AsyncSession, enrollment_id: int, *, today: date_type | None = None
) -> EnrollmentScheduleResponse:
    """Échéancier applicable et retard à date.

    L'accord passé avec la famille prime sur la grille de l'établissement :
    une famille qui respecte son propre échéancier ne doit pas apparaître en
    retard au motif qu'elle ne suit pas le calendrier standard.
    """
    today = today or date_type.today()
    year_id = await _academic_year_id(db, enrollment_id)

    total_mandatory = await repo.mandatory_total(db, enrollment_id)
    paid = await repo.total_paid(db, enrollment_id)

    negotiated = await repo.list_enrollment_plan(db, enrollment_id)
    if negotiated:
        source = SOURCE_NEGOTIATED
        rows = [(i.name, i.position, Decimal(str(i.amount)), i.due_date) for i in negotiated]
    else:
        grid = await repo.list_year_grid(db, year_id)
        if grid:
            source = SOURCE_STANDARD
            amounts = split_by_percentage(
                total_mandatory, [Decimal(str(g.percentage)) for g in grid]
            )
            rows = [
                (g.name, g.position, amount, g.due_date)
                for g, amount in zip(grid, amounts, strict=True)
            ]
        else:
            # Aucune tranche configurée : on n'invente pas d'échéance, et donc
            # personne n'est en retard. Accuser une famille sur la base d'un
            # calendrier que l'école n'a pas défini serait faux.
            source = SOURCE_NONE
            rows = []

    arrears = compute_arrears([(due, amount) for _n, _p, amount, due in rows], paid, today)

    return EnrollmentScheduleResponse(
        enrollment_id=enrollment_id,
        source=source,
        total_mandatory=float(total_mandatory),
        total_paid=float(paid),
        due_so_far=float(arrears.due_so_far),
        late_amount=float(arrears.late_amount),
        is_late=arrears.is_late,
        next_due_date=arrears.next_due_date,
        next_due_amount=(
            float(arrears.next_due_amount) if arrears.next_due_amount is not None else None
        ),
        lines=[
            ScheduleLine(
                name=name,
                position=position,
                amount=float(amount),
                due_date=due_date,
                is_due=due_date <= today,
            )
            for name, position, amount, due_date in rows
        ],
    )
