"""Calculs purs des tranches — répartition et retard.

Isolés de la base : ce sont les deux règles que l'école conteste quand un
parent proteste, elles doivent être lisibles et testables seules.
"""

from dataclasses import dataclass
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal

# Le FCFA n'a pas de subdivision en usage : on répartit en francs entiers.
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


def percentages_sum(percentages: list[Decimal]) -> Decimal:
    return sum(percentages, Decimal("0"))


def is_complete_grid(percentages: list[Decimal]) -> bool:
    """Une grille doit couvrir exactement le total dû, ni plus ni moins."""
    return bool(percentages) and percentages_sum(percentages) == _HUNDRED


def split_by_percentage(total: Decimal, percentages: list[Decimal]) -> list[Decimal]:
    """Répartit `total` selon les pourcentages, sans perdre ni créer un franc.

    Chaque tranche est arrondie au franc, sauf la dernière qui absorbe le reste.
    Sans ce rattrapage, trois tranches de 33,33 % sur 100 000 F laisseraient un
    franc dans la nature, et le solde d'une famille à jour n'atteindrait jamais
    zéro — ce qui la ferait apparaître éternellement en retard d'un franc.
    """
    if not percentages:
        return []

    amounts: list[Decimal] = []
    for pct in percentages[:-1]:
        amounts.append((total * pct / _HUNDRED).quantize(_ONE, rounding=ROUND_HALF_UP))

    amounts.append(total - sum(amounts, Decimal("0")))
    return amounts


@dataclass(frozen=True, slots=True)
class Arrears:
    """État de retard d'une inscription à une date donnée."""

    due_so_far: Decimal
    paid: Decimal
    late_amount: Decimal
    next_due_date: date_type | None
    next_due_amount: Decimal | None

    @property
    def is_late(self) -> bool:
        return self.late_amount > 0


def compute_arrears(
    schedule: list[tuple[date_type, Decimal]], paid: Decimal, today: date_type
) -> Arrears:
    """Retard = ce qui est déjà exigible, moins ce qui a été versé.

    Les deux dimensions comptent, et c'est le point : une famille qui a versé
    moins que le total dû n'est **pas** en retard tant que l'échéance suivante
    n'est pas arrivée. Ne regarder que le montant ferait apparaître en impayé
    toutes les familles qui paient en plusieurs fois, c'est-à-dire presque
    toutes.

    `schedule` est supposé trié par date d'échéance.
    """
    due_so_far = sum((amount for due_date, amount in schedule if due_date <= today), Decimal("0"))
    late_amount = max(Decimal("0"), due_so_far - paid)

    next_due = next(((d, a) for d, a in schedule if d > today), None)

    return Arrears(
        due_so_far=due_so_far,
        paid=paid,
        late_amount=late_amount,
        next_due_date=next_due[0] if next_due else None,
        next_due_amount=next_due[1] if next_due else None,
    )
