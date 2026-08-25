"""Résolution de l'échéancier d'une inscription et de son état de retard."""

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enrollment import Enrollment
from app.models.installment import FeeInstallment, FeeInstallmentKind
from app.repositories import installment_repository as repo
from app.schemas.installment import EnrollmentScheduleResponse, ScheduleLine
from app.services import fees_paid
from app.services.installments._math import GridLine, compute_arrears, resolve_grid_amounts

# Trois provenances possibles pour un échéancier, dans cet ordre de priorité.
SOURCE_NEGOTIATED = "negotiated"
SOURCE_STANDARD = "standard"
SOURCE_NONE = "none"


def _to_grid_line(row: FeeInstallment) -> GridLine:
    """Traduit une ligne de grille en donnée de calcul, sans lire son nom.

    La colonne non renseignée vaut zéro plutôt que `None` : une tranche dont
    l'écriture a été vidée en base ne doit pas faire tomber l'échéancier de
    toute une école, elle doit compter pour rien.
    """
    is_fixed = row.kind == FeeInstallmentKind.FIXED.value
    raw = row.amount if is_fixed else row.percentage
    return GridLine(is_fixed=is_fixed, value=Decimal(str(raw)) if raw is not None else Decimal("0"))


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
    paid = await fees_paid.paid_on_mandatory(db, enrollment_id)

    negotiated = await repo.list_enrollment_plan(db, enrollment_id)
    if negotiated:
        source = SOURCE_NEGOTIATED
        rows = [(i.name, i.position, Decimal(str(i.amount)), i.due_date) for i in negotiated]
    else:
        grid = await repo.list_year_grid(db, year_id)
        if grid:
            source = SOURCE_STANDARD
            amounts = resolve_grid_amounts(total_mandatory, [_to_grid_line(g) for g in grid])
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

    # Ce que la grille ne planifie pas : une somme en francs qui ne couvre pas
    # tout le dû laisse un reliquat sans date. On l'affiche plutôt que de le
    # taire, sans le compter en retard — aucune échéance ne le réclame.
    scheduled = sum((amount for _n, _p, amount, _d in rows), Decimal("0"))
    unscheduled = max(Decimal("0"), total_mandatory - scheduled)

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
        unscheduled_amount=float(unscheduled),
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
