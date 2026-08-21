"""Service : composition + génération du bordereau journalier (PDF).

Compose le dict `data` attendu par `pdf.daily_cash_book.generate_daily_cash_book_pdf`
depuis tous les Payment d'une date donnée, et délègue au générateur PDF stateless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment
from app.models.fee import Payment, PaymentStatus
from app.repositories import cash_session_repository as cash_repo
from app.services._school_settings_helper import (
    load_school_settings_for_pdf as _get_school_settings,
)
from app.services.pdf import generate_daily_cash_book_pdf
from app.services.pdf._helpers import enum_value


async def _load_payments_for_day(
    db: AsyncSession, target_date: date, *, restrict_to_cashier_id: int | None = None
) -> list[Payment]:
    """Charge les paiements de la journée avec le nom de l'élève pour le PDF.

    `restrict_to_cashier_id` limite le bordereau à une seule caisse. Sans lui,
    un caissier imprimerait les versements de toute l'école : le paramètre
    `cashier_user_id` ne servait qu'à signer le document, pas à le filtrer.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    stmt = (
        select(Payment)
        .where(Payment.created_at >= day_start, Payment.created_at < day_end)
        .options(
            selectinload(Payment.enrollment).selectinload(Enrollment.student),
        )
        .order_by(Payment.created_at.asc())
    )
    if restrict_to_cashier_id is not None:
        stmt = stmt.where(Payment.received_by == restrict_to_cashier_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@dataclass(slots=True)
class CashierDayTotals:
    """Ce qu'une caisse a encaissé sur la journée, ventilé par moyen.

    Une dataclass et non un `dict[str, object]` : la version en dictionnaire
    demandait un `type: ignore` à chaque lecture d'un champ, et le générateur
    PDF n'avait aucun moyen de savoir qu'il manipulait des `Decimal`.
    """

    cashier_name: str
    count: int = 0
    total: Decimal = Decimal("0")
    by_method: dict[str, Decimal] = field(default_factory=dict)


def cashier_breakdown(payments: list[Payment], names: dict[int, str]) -> list[CashierDayTotals]:
    """Qui a encaissé quoi, et sous quelle forme.

    C'est ce que le comptable cherche en ouvrant le bordereau consolidé :
    non pas une somme unique, mais la ventilation caisse par caisse. Sans
    elle, rapprocher un dépôt bancaire d'une caisse précise obligeait à
    relire ligne à ligne le détail des versements.

    Seuls les versements validés comptent : un versement annulé n'a pas
    alimenté le tiroir, et l'inclure gonflerait le total à rapprocher.
    """
    per_cashier: dict[int | None, CashierDayTotals] = {}
    for payment in payments:
        if enum_value(payment.status) != PaymentStatus.COMPLETED.value:
            continue
        key = payment.received_by
        entry = per_cashier.get(key)
        if entry is None:
            entry = CashierDayTotals(cashier_name=names.get(key, "—") if key else "—")
            per_cashier[key] = entry
        method = str(enum_value(payment.method) or "")
        entry.count += 1
        entry.total += payment.amount
        entry.by_method[method] = entry.by_method.get(method, Decimal("0")) + payment.amount
    return sorted(per_cashier.values(), key=lambda e: e.cashier_name)


def _student_full_name(payment: Payment) -> str:
    """Nom porté par la ligne du bordereau.

    Une colonne « Élève » remplie de tirets rendrait le document inutilisable
    au moment même où il sert le plus : quand on cherche à qui correspondait
    une somme encaissée il y a trois mois. D'où le repli sur le nom figé,
    recopié sur le versement avant que la fiche ne parte.
    """
    student = payment.enrollment.student if payment.enrollment is not None else None
    if student is not None:
        parts = [student.first_name or "", student.last_name or ""]
        nom = " ".join(p for p in parts if p).strip()
        if nom:
            return nom
    return payment.student_name_snapshot or "—"


async def get_daily_cash_book_pdf(
    db: AsyncSession,
    target_date: date,
    *,
    cashier_user_id: int | None = None,
    restrict_to_cashier: bool = False,
) -> bytes:
    """Génère le bordereau journalier en PDF pour la date donnée.

    `restrict_to_cashier` limite le document à la caisse de `cashier_user_id` —
    c'est le bordereau que le caissier imprime pour clôturer sa journée. Sans
    lui, le document couvre toutes les caisses : la vue du comptable.
    """
    payments = await _load_payments_for_day(
        db,
        target_date,
        restrict_to_cashier_id=cashier_user_id if restrict_to_cashier else None,
    )

    # Un seul aller-retour pour tous les noms, la fiche Personnel faisant foi.
    # `_resolve_cashier_name` recomposait ici un nom depuis l'email et le
    # bordereau sortait signé « accountant6 » ou « cashier3 » — un identifiant
    # technique en guise de signature sur une pièce comptable.
    cashier_ids = sorted({p.received_by for p in payments if p.received_by})
    if cashier_user_id and cashier_user_id not in cashier_ids:
        cashier_ids.append(cashier_user_id)
    names = await cash_repo.cashier_names(db, cashier_ids)

    payment_rows: list[dict] = []
    totals_by_method: dict[str, Decimal] = {}
    total_general = Decimal("0")
    count_completed = 0
    count_cancelled = 0

    for p in payments:
        # FIX bug enum : extraire .value pour obtenir 'cash' au lieu de PaymentMethod.CASH
        p_method = enum_value(p.method)
        p_status = enum_value(p.status)
        payment_rows.append(
            {
                "id": p.id,
                "created_at": p.created_at,
                "student_name": _student_full_name(p),
                "cashier_name": names.get(p.received_by, "—") if p.received_by else "—",
                "method": p_method,
                "reference": p.reference,
                "amount": p.amount,
                "status": p_status,
            }
        )
        if p_status == PaymentStatus.COMPLETED.value:
            totals_by_method[p_method] = totals_by_method.get(p_method, Decimal("0")) + p.amount
            total_general += p.amount
            count_completed += 1
        elif p_status == PaymentStatus.CANCELLED.value:
            count_cancelled += 1

    school = await _get_school_settings(db)
    issued_by_name = names.get(cashier_user_id, "—") if cashier_user_id else "—"

    data = {
        "date": datetime.combine(target_date, time.min),
        # Le document consolidé couvre plusieurs caisses : il ne peut pas être
        # attribué à un caissier, et surtout pas à celui qui l'imprime. Le
        # générateur s'appuie sur ce drapeau pour choisir l'en-tête, la
        # ventilation par caisse et le bloc de signature.
        "consolidated": not restrict_to_cashier,
        "cashier_name": issued_by_name if restrict_to_cashier else None,
        "issued_by_name": issued_by_name,
        "payments": payment_rows,
        "by_cashier": cashier_breakdown(payments, names),
        "totals_by_method": totals_by_method,
        "total_general": total_general,
        "count_completed": count_completed,
        "count_cancelled": count_cancelled,
        "issued_at": datetime.utcnow(),
    }
    return generate_daily_cash_book_pdf(data, school)
