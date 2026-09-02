"""Journal des versements — le jeu de données que PDF et Excel partagent.

Les deux documents sortent du même assemblage. C'est la seule façon d'être sûr
qu'ils disent la même chose : deux compositions écrites séparément dérivent, et
le jour où elles dérivent, personne ne sait laquelle croire.

Deux invariants portent tout le reste :

- **Le total est la somme des lignes retenues.** La ventilation par moyen de
  paiement est construite dans la même boucle que le total général, à partir de
  la valeur réellement portée par le versement. Aucune liste de moyens n'est
  figée ici : un moyen ajouté demain apparaît de lui-même, avec son montant.
  Une ventilation bâtie sur une liste écrite à la main aurait fait disparaître
  la colonne du nouveau moyen sans rien signaler — et un total qui ne se
  décompose plus est un total faux.

- **Seuls les versements validés font de l'argent.** Les autres états sont
  comptés, nommément, et jamais additionnés au total. Là encore sans
  fourre-tout : chaque état est compté sous son propre nom, y compris un état
  qui n'existait pas quand ces lignes ont été écrites.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee import Payment
from app.repositories import payment_journal_repository as repo
from app.repositories.cash_session_repository import METHODS_ORDER
from app.repositories.payment_filters import PaymentFilters
from app.schemas.payment import CashierOption
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.exports.payments_journal_xlsx import generate_payments_journal_xlsx
from app.services.payments._cashier import cashier_label, cashier_name
from app.services.payments._response import student_identity
from app.services.payments.journal_data import (
    COMPLETED,
    UNALLOCATED,
    FeeShare,
    GroupTotal,
    JournalLine,
    PaymentsJournal,
)
from app.services.payments.journal_labels import (
    filters_label as describe_filters,
)
from app.services.payments.journal_labels import (
    period_label as describe_period,
)
from app.services.payments.journal_labels import (
    scope_label as describe_scope,
)
from app.services.pdf._helpers import enum_value
from app.services.pdf.payments_journal import generate_payments_journal_pdf

# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------


def _fee_shares(payment: Payment) -> tuple[FeeShare, ...]:
    """Ce sur quoi le versement a été imputé, et pour combien sur chacun.

    Toutes les catégories, jamais un extrait : la somme des parts doit se
    relire dans le montant de la ligne. Un versement de 85 000 F réparti sur
    trois frais se décomposait auparavant en « Scolarité (+2) », et les deux
    catégories cachées ne figuraient nulle part ailleurs dans le document.

    Les parts sont cumulées **par catégorie** et non par frais : une famille
    qui règle trois tranches de scolarité lit « Scolarité 60 000 », pas trois
    lignes identiques qu'il faudrait additionner de tête.

    L'ordre est celui des imputations, qui est celui des priorités de frais :
    le trier autrement le rendrait indépendant de la logique de cascade, et
    deux versements identiques se liraient dans deux ordres différents.
    """
    parts: dict[str, Decimal] = {}
    for allocation in getattr(payment, "allocations", None) or []:
        ef = getattr(allocation, "enrollment_fee", None)
        fv = getattr(ef, "fee_variant", None) if ef is not None else None
        cat = getattr(fv, "category", None) if fv is not None else None
        nom = getattr(cat, "name", None)
        if not nom:
            continue
        montant = Decimal(str(getattr(allocation, "amount", 0) or 0))
        parts[nom] = parts.get(nom, Decimal("0")) + montant

    shares = [FeeShare(category_name=nom, amount=montant) for nom, montant in parts.items()]

    # Ce que le versement porte au-delà de ses imputations. L'invariant
    # comptable veut que ce reste soit nul, et il l'est ; mais un versement
    # ancien peut n'avoir aucune allocation, et la cellule disait alors « — »
    # sur de l'argent réellement encaissé. Le nommer coûte une ligne et évite
    # qu'un total d'export ne se décompose pas.
    montant_total = Decimal(str(getattr(payment, "amount", 0) or 0))
    reste = montant_total - sum((share.amount for share in shares), Decimal("0"))
    if reste > 0:
        shares.append(FeeShare(category_name=UNALLOCATED, amount=reste))

    return tuple(shares)


def _to_line(payment: Payment) -> JournalLine:
    nom, matricule, _photo, _supprime = student_identity(payment)
    return JournalLine(
        id=payment.id,
        created_at=payment.created_at,
        student_name=nom or "—",
        student_matricule=matricule,
        fee_shares=_fee_shares(payment),
        method=enum_value(payment.method) or "",
        reference=payment.reference,
        amount=payment.amount,
        status=enum_value(payment.status) or "",
        cashier=cashier_label(getattr(payment, "received_by_user", None)),
    )


def _ordered_methods(keys: set[str]) -> list[str]:
    """Les moyens rencontrés, dans l'ordre de l'écran puis les nouveaux venus.

    Un moyen que cette version ne connaît pas passe en fin de liste, sous son
    propre nom. Il n'est ni ignoré ni fondu dans une ligne « Autres » : c'est
    exactement ce genre de repli qui fausse un total sans le dire.
    """
    connus = [m for m in METHODS_ORDER if m in keys]
    nouveaux = sorted(keys - set(METHODS_ORDER))
    return connus + nouveaux


def _group(pairs: list[tuple[str, Decimal]], order: list[str] | None = None) -> list[GroupTotal]:
    counts: dict[str, int] = {}
    totals: dict[str, Decimal] = {}
    for key, amount in pairs:
        counts[key] = counts.get(key, 0) + 1
        totals[key] = totals.get(key, Decimal("0")) + amount
    keys = order if order is not None else sorted(totals)
    return [GroupTotal(key=k, count=counts[k], total=totals[k]) for k in keys]


def build_journal(
    payments: list[Payment],
    *,
    period_label: str,
    filters_label: str,
    scope_label: str,
    school: dict[str, Any],
    total_found: int,
    issued_at: datetime | None = None,
) -> PaymentsJournal:
    """Compose le journal à partir des versements déjà sélectionnés."""
    lines = [_to_line(p) for p in payments]

    counts_by_status: dict[str, int] = {}
    encaisses: list[JournalLine] = []
    for line in lines:
        counts_by_status[line.status] = counts_by_status.get(line.status, 0) + 1
        if line.status == COMPLETED:
            encaisses.append(line)

    total_encaisse = sum((line.amount for line in encaisses), Decimal("0"))
    par_moyen = _group(
        [(line.method, line.amount) for line in encaisses],
        order=_ordered_methods({line.method for line in encaisses}),
    )
    par_caissier = _group([(line.cashier, line.amount) for line in encaisses])

    return PaymentsJournal(
        lines=lines,
        by_method=par_moyen,
        by_cashier=par_caissier,
        total_encaisse=total_encaisse,
        counts_by_status=counts_by_status,
        period_label=period_label,
        filters_label=filters_label,
        scope_label=scope_label,
        issued_at=issued_at or datetime.now(),
        truncated_from=total_found if total_found > len(lines) else None,
        school=school,
    )


async def load_journal(
    db: AsyncSession,
    *,
    filters: PaymentFilters,
    restricted: bool,
) -> PaymentsJournal:
    """Charge et compose le journal correspondant aux critères donnés.

    `restricted` dit si l'appelant lit sa seule caisse. Le filtre lui-même est
    déjà porté par `filters.received_by`, résolu en amont par
    `app.services.payments.scope` : ici on n'en tire que la phrase d'en-tête,
    pour que le document dise à voix haute ce qu'il couvre.
    """
    total_found = await repo.count_for_journal(db, filters)
    payments = await repo.list_for_journal(db, filters)
    school = await load_school_settings_for_pdf(db)
    porteur = (
        await repo.get_cashier(db, filters.received_by) if filters.received_by is not None else None
    )
    return build_journal(
        payments,
        period_label=describe_period(filters.date_from, filters.date_to),
        filters_label=describe_filters(status=filters.status, method=filters.method),
        scope_label=describe_scope(restricted=restricted, cashier_name=cashier_name(porteur)),
        school=school,
        total_found=total_found,
    )


# ---------------------------------------------------------------------------
# Sorties
# ---------------------------------------------------------------------------


async def get_journal_pdf(db: AsyncSession, **kwargs: Any) -> bytes:
    """Journal des versements en PDF, au gabarit officiel de l'établissement."""
    journal = await load_journal(db, **kwargs)
    return generate_payments_journal_pdf(journal, journal.school)


async def get_journal_xlsx(db: AsyncSession, **kwargs: Any) -> bytes:
    """Journal des versements en classeur Excel, aux couleurs de l'établissement."""
    journal = await load_journal(db, **kwargs)
    return generate_payments_journal_xlsx(journal, journal.school)


async def list_cashier_options(db: AsyncSession) -> list[CashierOption]:
    """Les encaisseurs proposables dans le filtre « Encaissé par »."""
    users = await repo.list_cashiers(db)
    options = [CashierOption(id=user.id, name=cashier_name(user) or user.email) for user in users]
    return sorted(options, key=lambda option: option.name.casefold())


async def own_cashier_option(db: AsyncSession, user_id: int) -> list[CashierOption]:
    """La seule caisse qu'un appelant cloisonné peut lire : la sienne.

    Renvoyer une liste plutôt qu'un objet garde un contrat unique pour
    l'écran, qui n'a alors pas à connaître les droits de celui qui l'ouvre.
    La liste est vide si le compte n'a jamais encaissé — un filtre qui
    proposerait une entrée sans aucune ligne derrière serait une fausse piste.
    """
    user = await repo.get_cashier(db, user_id)
    if user is None:
        return []
    return [CashierOption(id=user.id, name=cashier_name(user) or user.email)]
