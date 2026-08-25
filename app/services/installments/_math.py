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
    """Les pourcentages d'une grille doivent couvrir exactement l'assiette.

    Ne porte que sur les tranches exprimées en pourcentage : ce sont elles qui
    se partagent le reste, et elles doivent s'en partager la totalité. Une
    somme inférieure laisserait une part des frais sans échéance, une somme
    supérieure réclamerait plus que le montant dû.
    """
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
class GridLine:
    """Une ligne de grille prête à être chiffrée, sans rien savoir de la base.

    `is_fixed` distingue les deux écritures possibles : `value` est alors des
    francs, sinon c'est un pourcentage.
    """

    is_fixed: bool
    value: Decimal


def resolve_grid_amounts(total: Decimal, lines: list[GridLine]) -> list[Decimal]:
    """Chiffre une grille mixte sur l'assiette d'un élève, dans l'ordre reçu.

    **La règle, en une phrase : les montants fermes se prélèvent d'abord sur
    le total obligatoire, les pourcentages se répartissent sur ce qui reste.**
    Un pourcentage porte donc sur le solde après montants fermes, jamais sur
    le total. C'est ce qui rend la grille lisible pour une directrice : elle
    pose en francs ce qu'elle connaît — l'inscription, annoncée telle quelle
    dans sa brochure — et laisse les pourcentages absorber la scolarité, qui
    change d'un niveau à l'autre.

    Sur la brochure de l'école pilote, une 6e non affectée doit 125 000 F
    (inscription 37 000 + scolarité 70 000 + tenue 18 000). La grille
    « Inscription 37 000 F ferme, puis 35 / 35 / 30 % » donne donc 37 000, puis
    30 800, 30 800 et 26 400 : les trois pourcentages se partagent les 88 000 F
    restants, pas les 125 000 du total.

    Deux garde-fous, dans le même esprit que le reste du module :

    - **Un montant ferme ne réclame jamais plus que l'élève ne doit.** Les
      montants sont prélevés dans l'ordre des échéances et bornés par ce qui
      reste ; une grille en francs bâtie pour un non affecté ne peut donc pas
      présenter à un affecté subventionné une dette qu'il n'a pas. Les
      échéances au-delà tombent à zéro et restent affichées : une ligne
      annoncée par l'école qui disparaîtrait de l'écran serait plus troublante
      qu'une ligne à 0 F.
    - **Ce qui n'est couvert par aucune ligne reste sans échéance.** Une grille
      faite uniquement de montants fermes qui ne couvrent pas tout le dû laisse
      un reliquat non planifié ; on ne lui invente pas de date, exactement
      comme une école sans grille du tout n'accuse personne.

    Une grille entièrement en pourcentages retombe sur l'ancien calcul au franc
    près : aucun montant ferme n'étant prélevé, le reste vaut le total.
    """
    if not lines:
        return []

    remaining = max(total, Decimal("0"))

    amounts: list[Decimal | None] = [None] * len(lines)
    for index, line in enumerate(lines):
        if not line.is_fixed:
            continue
        taken = min(max(line.value, Decimal("0")), remaining)
        amounts[index] = taken
        remaining -= taken

    percentage_indexes = [i for i, line in enumerate(lines) if not line.is_fixed]
    shares = split_by_percentage(remaining, [lines[i].value for i in percentage_indexes])
    for index, share in zip(percentage_indexes, shares, strict=True):
        amounts[index] = share

    return [amount if amount is not None else Decimal("0") for amount in amounts]


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
