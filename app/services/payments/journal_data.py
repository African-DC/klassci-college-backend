"""Ce qu'est un journal des versements, indépendamment de qui le compose.

Ces formes vivent seules pour que les deux fabriques de documents — le PDF et
le classeur — n'aient pas à importer le service qui les remplit. Sans cette
séparation, chaque générateur dépendait du service et le service de chaque
générateur : un cycle d'imports que rien ne casse au démarrage tant que
l'ordre de chargement reste le même, et qui casse le jour où il change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.fee import PaymentStatus

#: L'état qui fait entrer un versement dans un total. Les autres sont comptés,
#: nommément, mais jamais additionnés.
COMPLETED = PaymentStatus.COMPLETED.value


@dataclass(frozen=True, slots=True)
class JournalLine:
    """Une ligne du journal, telle qu'elle sera imprimée."""

    id: int
    created_at: datetime
    student_name: str
    student_matricule: str | None
    fee_label: str
    method: str
    reference: str | None
    amount: Decimal
    status: str
    cashier: str


@dataclass(frozen=True, slots=True)
class GroupTotal:
    """Un sous-total : combien de versements validés, pour quelle somme."""

    key: str
    count: int
    total: Decimal


@dataclass(slots=True)
class PaymentsJournal:
    """Le journal complet, prêt à composer."""

    lines: list[JournalLine]
    by_method: list[GroupTotal]
    by_cashier: list[GroupTotal]
    total_encaisse: Decimal
    counts_by_status: dict[str, int]
    period_label: str
    filters_label: str
    scope_label: str
    issued_at: datetime
    truncated_from: int | None = None
    school: dict[str, Any] = field(default_factory=dict)

    @property
    def count_encaisse(self) -> int:
        return self.counts_by_status.get(COMPLETED, 0)
