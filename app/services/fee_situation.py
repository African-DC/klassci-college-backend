"""La situation financière d'une inscription : dû, versé, reste, par frais.

Le tableau que lisent l'état des frais et le reçu de versement. Il n'invente
aucun montant : le versé vient de `fees_paid`, seule vérité du projet sur ce
qu'une famille a réellement payé, et le dû vient du frais lui-même.

Ce module existe parce que la même agrégation était sur le point d'être écrite
une seconde fois pour le reçu. Deux boucles qui soustraient les mêmes chiffres
finissent par diverger sur un cas limite — un frais exonéré, un trop-perçu —
et l'école se retrouve avec deux documents officiels qui se contredisent.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.fee import cash_remaining, is_in_kind
from app.services import fee_entitlements as entitlements
from app.services import fees_paid
from app.services.pdf._helpers import enum_value

# Au-delà, on ne devine pas la priorité de la catégorie : elle passe en queue.
_PRIORITE_PAR_DEFAUT = 100


@dataclass(frozen=True)
class FeeLine:
    """Une ligne du tableau : un frais, ce qu'il coûte, ce qui reste dessus."""

    category_name: str
    priority: int
    # Ce que la ligne achete, pas seulement ce qu'elle coute. Calcule ici pour
    # que le recu et l'etat des frais promettent mot pour mot la meme chose.
    entitlements: str
    due: Decimal
    paid: Decimal
    remaining: Decimal
    status: str


@dataclass(frozen=True)
class FeeSituation:
    """Le tableau complet et ses totaux."""

    lines: tuple[FeeLine, ...]
    total_due: Decimal
    total_paid: Decimal
    total_remaining: Decimal

    @property
    def completion_rate(self) -> float:
        """Part du dû déjà réglée, en pourcentage. 0 si rien n'est dû."""
        if self.total_due <= 0:
            return 0.0
        return float(self.total_paid / self.total_due * 100)


def _category(fee: object) -> object | None:
    variant = getattr(fee, "fee_variant", None)
    return getattr(variant, "category", None) if variant is not None else None


def situation_from_fees(fees: Iterable[object], paid_by_fee: dict[int, Decimal]) -> FeeSituation:
    """Compose le tableau depuis des frais déjà chargés et le versé par frais.

    `paid_by_fee` vient de `fees_paid.paid_by_enrollment` : on ne resomme rien
    ici. Un frais absent du dictionnaire n'a simplement rien reçu.

    Le reste est borné à zéro. Un trop-perçu se lit sur le versé, pas sur un
    reste négatif : « il vous reste -5 000 F à payer » n'est pas une phrase
    qu'un parent doit avoir à interpréter au guichet.
    """
    ordered = sorted(
        fees,
        key=lambda f: (
            getattr(_category(f), "priority", _PRIORITE_PAR_DEFAUT) or _PRIORITE_PAR_DEFAUT,
            getattr(f, "id", 0) or 0,
        ),
    )

    lines: list[FeeLine] = []
    total_due = Decimal("0")
    total_paid = Decimal("0")
    total_remaining = Decimal("0")
    for fee in ordered:
        due = Decimal(str(getattr(fee, "amount", 0) or 0))
        paid = paid_by_fee.get(int(getattr(fee, "id", 0) or 0), Decimal("0"))
        raw_status = getattr(fee, "status", "") or ""
        status = str(enum_value(raw_status) or "")
        remaining = cash_remaining(status, due, paid)
        category = _category(fee)
        lines.append(
            FeeLine(
                category_name=getattr(category, "name", "") or "",
                priority=getattr(category, "priority", _PRIORITE_PAR_DEFAUT)
                or _PRIORITE_PAR_DEFAUT,
                entitlements=entitlements.receipt_line(
                    entitlements.read(category),
                    getattr(category, "description", None),
                ),
                due=due,
                paid=paid,
                remaining=remaining,
                status=status,
            )
        )
        # Le reçu montre l'argent, y compris versé puis exonéré. Un dépôt
        # en nature n'est pas de l'argent : hors grand total.
        if not is_in_kind(status):
            total_due += due
            total_paid += paid
        total_remaining += remaining

    return FeeSituation(
        lines=tuple(lines),
        total_due=total_due,
        total_paid=total_paid,
        total_remaining=total_remaining,
    )


async def load_situation(db: AsyncSession, enrollment_id: int) -> FeeSituation:
    """Charge les frais d'une inscription et compose sa situation financière.

    Deux requêtes : les frais avec leur catégorie, puis le versé par frais.
    Pas une requête par frais — le reçu s'imprime au guichet, devant la
    famille.
    """
    from app.models.fee import EnrollmentFee, FeeVariant

    stmt = (
        select(EnrollmentFee)
        .where(EnrollmentFee.enrollment_id == enrollment_id)
        .options(selectinload(EnrollmentFee.fee_variant).selectinload(FeeVariant.category))
    )
    fees: Sequence[EnrollmentFee] = (await db.execute(stmt)).scalars().all()
    return situation_from_fees(fees, await fees_paid.paid_by_enrollment(db, enrollment_id))
