"""Preview UX caissier — calcule l'allocation sans rien écrire.

Appelé par le FE avant submit pour montrer le breakdown (qui reçoit
combien, surplus éventuel, raison de rejet). Read-only — pas de
verrouillage row, pas de commit.
"""

from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.fee import EnrollmentFee, EnrollmentFeeStatus, cash_remaining, is_not_cash_due
from app.repositories import payment_repository as repo
from app.schemas.fee import FeeEntitlement
from app.schemas.payment import (
    AllocationPreviewLine,
    AllocationPreviewProblem,
    AllocationPreviewResponse,
    PaymentAllocationItem,
)
from app.services import fee_entitlements as entitlements
from app.services import fees_paid
from app.services.payments._allocation import resolve_allocation


def _resolve_category(fee: EnrollmentFee) -> tuple[str, int, list[FeeEntitlement]]:
    """Extrait (name, priority, contrepartie) de la category liée. Defaults safe."""
    fv = getattr(fee, "fee_variant", None)
    if fv is not None:
        cat = getattr(fv, "category", None)
        if cat is not None:
            return cat.name, cat.priority, entitlements.read(cat)
    return "", 100, []


def _status_after(fee: EnrollmentFee, paid_after: Decimal) -> str:
    """Calcule le statut prévu après allocation hypothétique."""
    if is_not_cash_due(fee.status):
        return fee.status
    if paid_after >= fee.amount:
        return EnrollmentFeeStatus.PAID.value
    if paid_after > 0:
        return EnrollmentFeeStatus.PARTIAL.value
    return EnrollmentFeeStatus.PENDING.value


async def preview_allocation(
    db: AsyncSession,
    enrollment_id: int,
    amount: Decimal,
    *,
    allocations: Iterable[PaymentAllocationItem] = (),
) -> AllocationPreviewResponse:
    """Montre comment `amount` serait alloué sans rien écrire.

    Inclut le surplus et la raison de rejet (décision Marcel #2 : reject
    par défaut en P0).

    `allocations` porte la répartition que le caissier a nommée. Absente, l'aperçu
    montre la cascade par priorité, comme il l'a toujours fait. Présente, c'est
    `resolve_allocation` qui répond, la même fonction que l'enregistrement
    appellera : l'écran ne rejoue plus le calcul de son côté, il affiche celui
    du serveur.

    Ce qui empêcherait d'enregistrer est **rendu** et non levé. Le caissier
    tape, l'aperçu explique, rien n'est encore écrit : une exception blanchirait
    l'écran à chaque frappe intermédiaire.
    """
    if amount <= 0:
        raise BusinessValidationError("amount must be positive")

    fees = await repo.get_enrollment_fees_ordered_by_priority(db, enrollment_id)
    if not fees:
        return AllocationPreviewResponse(
            enrollment_id=enrollment_id,
            amount=amount,
            total_remaining_before=Decimal("0"),
            total_remaining_after=Decimal("0"),
            surplus=amount,
            can_record=False,
            reject_reason="Aucun frais configuré pour cette inscription",
            lines=[],
        )

    # Une requete groupee pour toute l'inscription, pas une par frais : un
    # apercu sur six frais coutait six allers-retours a la base pendant que
    # le caissier attendait devant la famille.
    deja_verse = await fees_paid.paid_by_enrollment(db, enrollment_id)
    fees_with_paid: list[tuple[EnrollmentFee, Decimal]] = [
        (fee, deja_verse.get(fee.id, Decimal("0"))) for fee in fees
    ]

    total_remaining_before = sum(
        (cash_remaining(f.status, f.amount, paid) for f, paid in fees_with_paid),
        Decimal("0"),
    )

    # La meme porte que l'enregistrement, sur les memes donnees : ce que
    # l'apercu annonce est exactement ce que la caisse acceptera.
    issue = resolve_allocation(
        amount,
        fees_with_paid,
        ((ligne.enrollment_fee_id, ligne.amount) for ligne in allocations),
    )
    nommees, problems, surplus = issue.directed, issue.problems, issue.surplus
    split_map = {fee.id: allocated for fee, allocated in issue.splits}

    lines: list[AllocationPreviewLine] = []
    for fee, paid in fees_with_paid:
        allocated = split_map.get(fee.id, Decimal("0"))
        paid_after = paid + allocated
        cat_name, cat_priority, cat_entitlements = _resolve_category(fee)
        lines.append(
            AllocationPreviewLine(
                enrollment_fee_id=fee.id,
                fee_category_name=cat_name,
                fee_category_entitlements=cat_entitlements,
                fee_category_priority=cat_priority,
                fee_total=fee.amount,
                fee_paid_before=paid,
                cash_remaining_before=cash_remaining(fee.status, fee.amount, paid),
                directed=nommees.get(fee.id, Decimal("0")),
                allocated=allocated,
                fee_paid_after=paid_after,
                status_after=_status_after(fee, paid_after),
            )
        )

    directed_total = sum(nommees.values(), Decimal("0"))
    allocated_total = sum(split_map.values(), Decimal("0"))
    can_record = not problems and surplus <= 0
    reject_reason = None
    if problems:
        reject_reason = problems[0].message
    elif not can_record:
        reject_reason = (
            f"Montant versé ({amount}) supérieur à la dette restante "
            f"({total_remaining_before}). Surplus : {surplus}."
        )

    return AllocationPreviewResponse(
        enrollment_id=enrollment_id,
        amount=amount,
        total_remaining_before=total_remaining_before,
        total_remaining_after=max(total_remaining_before - amount, Decimal("0")),
        directed_total=directed_total,
        cascaded_total=max(allocated_total - directed_total, Decimal("0")),
        surplus=max(surplus, Decimal("0")),
        can_record=can_record,
        reject_reason=reject_reason,
        problems=[
            AllocationPreviewProblem(enrollment_fee_id=p.enrollment_fee_id, message=p.message)
            for p in problems
        ],
        lines=lines,
    )
