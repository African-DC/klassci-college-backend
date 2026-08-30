"""Les encaissements de l'année scolaire et les journées de caisse qu'ils remplissent.

Trois partis pris expliquent la forme de ce module.

**On encaisse par le service, jamais par la table.** `record_enrollment_payment`
ouvre la journée du caissier, vérifie la dette restante, répartit le versement
sur les frais par ordre de priorité, écrit le journal d'audit et pose les
allocations. Un semis qui insérerait ses lignes à la main produirait des
versements sans imputation, donc des soldes de famille faux partout où ils
s'affichent.

**La date se déplace après coup, et c'est volontaire.** Le service horodate à
l'instant présent : c'est ce qu'il doit faire au guichet. Une école, elle, a
encaissé de septembre à juin. Le semis laisse donc le service écrire, puis
déplace l'horloge par une mise à jour ciblée sur le versement et ses
allocations. L'inverse, une date passée en paramètre, ouvrirait dans le service
une porte dérobée qui n'a aucune raison d'exister en production.

**La journée en cours reste ouverte.** Clôturer la caisse du jour interdirait
au service d'encaisser la moindre pièce ensuite, et la démonstration
commencerait par un refus. Les journées passées, elles, sont clôturées avec
l'écart qu'un tiroir réel finit toujours par accuser.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Date, case, cast, func, select, update

from app.cli.seed_demo.context import SeedContext, logger
from app.core.exceptions import BusinessValidationError
from app.models.cash_session import CashSession, CashSessionStatus, is_locked
from app.models.enrollment import Enrollment, EnrollmentStatus
from app.models.fee import (
    NOT_CASH_DUE,
    EnrollmentFee,
    FeeCategory,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentStatus,
)
from app.schemas.payment import EnrollmentPaymentCreate
from app.services.payments import record_enrollment_payment

#: Profil de règlement d'une famille : part de la dette réglée sur l'année, et
#: nombre de passages à la caisse pour y arriver. Une part ne verse rien du
#: tout, parce que les écrans d'impayés et de relance n'ont rien à montrer sur
#: une école entièrement à jour.
_PROFILES: tuple[tuple[tuple[str, int, int, int, int], int], ...] = (
    (("soldée", 100, 100, 3, 4), 35),
    (("en cours", 60, 85, 2, 3), 40),
    (("en retard", 25, 50, 1, 2), 18),
    (("inscription seule", 0, 0, 1, 1), 4),
    (("sans versement", 0, 0, 0, 0), 3),
)

#: Moyens de paiement, dans la répartition d'un privé abidjanais : le guichet
#: reste roi, le mobile money a pris la deuxième place, le chèque survit chez
#: les entreprises qui règlent la scolarité des enfants de leurs cadres.
_METHODS: tuple[tuple[PaymentMethod, int], ...] = (
    (PaymentMethod.CASH, 45),
    (PaymentMethod.MOBILE_MONEY, 30),
    (PaymentMethod.BANK_TRANSFER, 18),
    (PaymentMethod.CHEQUE, 7),
)

#: Les trois opérateurs de monnaie électronique du pays.
_WALLETS: tuple[str, ...] = ("WAVE", "OM", "MOMO")
_PREFIXES: dict[str, str] = {"cash": "ESP", "bank_transfer": "VIR", "cheque": "CHQ"}

#: Les versements se font en billets ronds : personne ne rend la monnaie sur
#: une scolarité.
_ROUND = Decimal("1000")

#: Écarts de caisse plausibles, en francs. Un tiroir qui tombe juste tous les
#: soirs de l'année ne ressemble à aucune caisse d'école.
_VARIANCES: tuple[Decimal, ...] = (
    Decimal("-5000"),
    Decimal("-2000"),
    Decimal("-1000"),
    Decimal("1000"),
    Decimal("2000"),
    Decimal("5000"),
)

#: Statuts qui laissent l'argent dans le tiroir. Copie assumée du périmètre de
#: `cash_session_repository.aggregate_day` : le théorique que l'écran calcule
#: et celui que le semis inscrit doivent porter sur les mêmes versements.
_COUNTED = (PaymentStatus.COMPLETED.value, PaymentStatus.PENDING.value)

#: Nombre de versements laissés à la date du jour, pour que la caisse ouverte
#: à l'écran ait quelque chose à montrer.
_TODAY_TAIL = 10


def _pick[T](rng: random.Random, weights: tuple[tuple[T, int], ...]) -> T:
    """Tire une valeur selon des poids entiers, de façon reproductible."""
    draw = rng.randint(1, sum(weight for _value, weight in weights))
    running = 0
    for value, weight in weights:
        running += weight
        if draw <= running:
            return value
    return weights[-1][0]


def _round_down(amount: Decimal) -> Decimal:
    """Rabote un montant au millier inférieur."""
    return (amount // _ROUND) * _ROUND


def _instalments(target: Decimal, count: int) -> list[Decimal]:
    """Découpe un objectif en versements ronds, le dernier soldant le reste.

    Le reliquat va sur le dernier passage, pas sur le premier : c'est ainsi
    qu'une famille solde, et cela garantit surtout que la somme des versements
    tombe exactement sur l'objectif. Sans quoi il resterait quelques francs de
    poussière, et un frais éternellement « partiel » à l'écran.
    """
    if target <= 0 or count <= 0:
        return []
    part = _round_down(target / count)
    if part < _ROUND:
        return [target]
    lines = [part] * (count - 1)
    last = target - sum(lines, Decimal("0"))
    return [*lines, last] if last > 0 else [target]


def _reference(method: PaymentMethod, enrollment_id: int, rank: int) -> str:
    """La référence du versement, qui sert aussi de clé de relance.

    Elle ne dépend que de l'inscription, du rang du versement et du moyen :
    deux exécutions produisent la même, et le semis retrouve donc ce qu'il a
    déjà encaissé au lieu de l'encaisser une seconde fois.
    """
    if method is PaymentMethod.MOBILE_MONEY:
        prefix = _WALLETS[(enrollment_id + rank) % len(_WALLETS)]
    else:
        prefix = _PREFIXES[method.value]
    return f"{prefix}-{enrollment_id:05d}-{rank}"


def _moment(ctx: SeedContext, rng: random.Random, rank: int, count: int) -> datetime:
    """Un jour ouvré plausible de l'année, aux heures d'ouverture du guichet.

    Les versements d'une même famille se répartissent dans l'ordre sur
    l'année : un solde daté d'octobre suivi d'un acompte de mai raconterait
    une histoire que personne ne peut suivre.
    """
    start = ctx.trimesters[0][1]
    end = min(ctx.today, ctx.trimesters[-1][2])
    span = max((end - start).days, 1)
    walked = int(span * (rank + 0.5) / max(count, 1)) + rng.randint(-5, 5)
    day = start + timedelta(days=min(max(walked, 0), span))
    while day.weekday() >= 5:  # samedi, dimanche
        day -= timedelta(days=1)
    if day > end:
        day = end
    minutes = rng.randint(7 * 60 + 30, 16 * 60 + 30)
    return datetime.combine(day, time(minutes // 60, minutes % 60))


async def _backdate(ctx: SeedContext, payment_id: int, when: datetime) -> None:
    """Déplace un versement et ses allocations à leur vraie date."""
    await ctx.db.execute(
        update(Payment).where(Payment.id == payment_id).values(created_at=when, updated_at=when)
    )
    await ctx.db.execute(
        update(PaymentAllocation)
        .where(PaymentAllocation.payment_id == payment_id)
        .values(created_at=when, updated_at=when)
    )


async def _dues_by_enrollment(ctx: SeedContext) -> dict[int, list[Decimal]]:
    """Ce que doit chaque inscription validée, frais par frais et par priorité.

    Les frais exonérés sont exclus : ils ne sont plus dus, et les compter
    ferait viser au semis une dette que la caisse refuserait d'encaisser.
    """
    stmt = (
        select(EnrollmentFee.enrollment_id, EnrollmentFee.amount, FeeCategory.priority)
        .join(Enrollment, Enrollment.id == EnrollmentFee.enrollment_id)
        .join(FeeCategory, FeeCategory.id == EnrollmentFee.fee_category_id)
        .where(
            Enrollment.academic_year_id == ctx.academic_year_id,
            Enrollment.status == EnrollmentStatus.VALIDE.value,
            EnrollmentFee.status.notin_(NOT_CASH_DUE),
        )
        .order_by(EnrollmentFee.enrollment_id, FeeCategory.priority)
    )
    dues: dict[int, list[Decimal]] = {}
    for enrollment_id, amount, _priority in (await ctx.db.execute(stmt)).all():
        dues.setdefault(int(enrollment_id), []).append(Decimal(str(amount)))
    return dues


async def _known_references(ctx: SeedContext) -> set[str]:
    """Les références déjà encaissées, chargées d'un coup.

    Une requête, et non une par versement envisagé : le semis en envisage
    plusieurs milliers.
    """
    rows = (await ctx.db.execute(select(Payment.reference))).scalars().all()
    return {str(row) for row in rows if row}


async def _cashiers(ctx: SeedContext) -> list[int]:
    """Les comptes qui tiennent la caisse et dont le tiroir est encore ouvert.

    Le service refuse d'encaisser sur une journée clôturée, et il a raison :
    l'écart signé le soir deviendrait faux la seconde suivante. Un locataire
    déjà démontré porte donc des caisses verrouillées — arrêtées par leur
    caissier, ou d'office à minuit. Les écarter ici, plutôt que de laisser le
    premier versement se heurter au refus, évite d'interrompre le semis sur un
    geste parfaitement légitime de l'application.
    """
    found = [
        user_id
        for role, user_id in sorted(ctx.staff_user_by_role.items())
        if role.startswith("cashier")
    ]
    candidates = list(dict.fromkeys([*found, ctx.actor_id]))

    # La date que le service retiendra au moment d'ouvrir la journée : la
    # sienne, pas celle du contexte, qui pourrait dater d'un semis commencé la
    # veille au soir.
    business_date = datetime.now().date()
    stmt = select(CashSession.cashier_user_id, CashSession.status).where(
        CashSession.business_date == business_date,
        CashSession.cashier_user_id.in_(candidates),
    )
    locked = {
        int(cashier_id)
        for cashier_id, status in (await ctx.db.execute(stmt)).all()
        if is_locked(status)
    }
    open_today = [user_id for user_id in candidates if user_id not in locked]
    if not open_today:
        raise BusinessValidationError(
            "Toutes les caisses du jour sont clôturées sur ce locataire : "
            "aucun versement ne peut être enregistré aujourd'hui. Régularisez "
            "une journée depuis l'écran de caisse, ou relancez demain."
        )
    for cashier_id in sorted(locked):
        logger.info(
            "Caisse du %s déjà clôturée pour le compte %s : écarté.", business_date, cashier_id
        )
    return open_today


def _plan_for(
    enrollment_id: int, amounts: list[Decimal]
) -> list[tuple[int, Decimal, PaymentMethod]]:
    """Le plan de règlement d'une famille, dérivé de sa seule inscription.

    **Le tirage part de l'identifiant de l'inscription, et l'objectif de la
    dette totale, jamais de ce qui reste à payer.** C'est ce qui rend le semis
    relançable. Un plan calculé sur le solde restant donnerait, au second
    passage, d'autres montants, donc d'autres références, donc des versements
    que le script ne reconnaîtrait pas comme les siens : il encaisserait une
    seconde fois toute l'année, et le taux de recouvrement dépasserait cent
    pour cent.

    Le profil « inscription seule » vise exactement le premier frais de la
    grille : c'est le geste minimal qui valide le dossier, et il est fréquent
    chez les familles qui remettent le reste à plus tard.
    """
    rng = random.Random(enrollment_id)
    label, low, high, lines_min, lines_max = _pick(rng, _PROFILES)
    total = sum(amounts, Decimal("0"))
    if label == "sans versement" or lines_max == 0 or total <= 0:
        return []

    if label == "inscription seule":
        target = amounts[0]
    else:
        share = rng.randint(low, high)
        target = total if share >= 100 else _round_down(total * share / 100)

    lines = _instalments(target, rng.randint(lines_min, lines_max))
    return [(rank, amount, _pick(rng, _METHODS)) for rank, amount in enumerate(lines, start=1)]


async def pay_school_year(ctx: SeedContext) -> None:
    """Étale sur l'année les versements de toutes les familles inscrites."""
    dues = await _dues_by_enrollment(ctx)
    if not dues:
        logger.info("Aucun frais posé sur l'année : rien à encaisser.")
        return

    known = await _known_references(ctx)
    cashiers = await _cashiers(ctx)
    recorded: list[int] = []

    for enrollment_id in sorted(dues):
        lines = _plan_for(enrollment_id, dues[enrollment_id])
        if not lines:
            continue

        clock = random.Random(enrollment_id * 7919)
        for rank, amount, method in lines:
            reference = _reference(method, enrollment_id, rank)
            if reference in known:
                continue
            try:
                payment = await record_enrollment_payment(
                    ctx.db,
                    enrollment_id,
                    EnrollmentPaymentCreate(
                        amount=amount, method=method.value, reference=reference, notes=None
                    ),
                    received_by=cashiers[(enrollment_id + rank) % len(cashiers)],
                )
            except BusinessValidationError as error:
                logger.info("Versement écarté sur l'inscription %s : %s", enrollment_id, error)
                continue
            known.add(reference)
            await _backdate(ctx, payment.id, _moment(ctx, clock, rank - 1, len(lines)))
            recorded.append(payment.id)
            ctx.tally("versements")

        await ctx.db.commit()

    await _bring_tail_to_today(ctx, recorded)
    logger.info("Encaissements posés : %s versements.", len(recorded))


async def _bring_tail_to_today(ctx: SeedContext, recorded: list[int]) -> None:
    """Ramène les derniers versements sur la journée en cours.

    Une caisse ouverte et vide ne se démontre pas : le caissier doit pouvoir
    ouvrir son écran, voir ses encaissements du matin, et clôturer devant la
    salle.
    """
    if not recorded:
        return
    for offset, payment_id in enumerate(recorded[-_TODAY_TAIL:]):
        moment = datetime.combine(ctx.today, time(8 + offset % 8, 15 * (offset % 4)))
        await _backdate(ctx, payment_id, moment)
    await ctx.db.commit()


def _variance(ctx: SeedContext) -> Decimal:
    """Un écart de caisse plausible : nul trois soirs sur quatre."""
    if ctx.rng.randint(1, 4) > 1:
        return Decimal("0")
    return ctx.rng.choice(_VARIANCES)


def _variance_note(variance: Decimal) -> str | None:
    """La ligne que le caissier écrit quand le tiroir ne tombe pas juste."""
    if variance == 0:
        return None
    if variance < 0:
        return "Manquant constaté au recomptage du soir, signalé à la comptabilité."
    return "Excédent constaté au recomptage du soir, reçu à retrouver et à saisir."


async def _cash_by_day(ctx: SeedContext) -> dict[tuple[int, date], Decimal]:
    """Le théorique espèces de chaque (caissier, journée) qui a vu un versement.

    Toute journée encaissée ouvre une session, mais seul le liquide entre dans
    le théorique : un virement bancaire ne se recompte pas dans un tiroir.
    """
    cash_only = case((Payment.method == PaymentMethod.CASH.value, Payment.amount), else_=0)
    stmt = (
        select(
            Payment.received_by,
            cast(Payment.created_at, Date),
            func.coalesce(func.sum(cash_only), 0),
        )
        .where(Payment.received_by.is_not(None), Payment.status.in_(_COUNTED))
        .group_by(Payment.received_by, cast(Payment.created_at, Date))
    )
    return {
        (int(cashier_id), business_day): Decimal(str(total or 0))
        for cashier_id, business_day, total in (await ctx.db.execute(stmt)).all()
    }


def _is_closed(session: CashSession) -> bool:
    """Vrai si la journée est déjà verrouillée, quelle que soit sa forme lue.

    Clôturée par son caissier ou d'office à minuit : dans les deux cas la
    journée est arrêtée. Une journée clôturée d'office n'a justement PAS été
    comptée ; lui inventer ici un montant et un écart effacerait la seule
    information qu'elle porte, à savoir que personne n'a ouvert le tiroir.
    """
    return is_locked(session.status)


async def settle_cash_days(ctx: SeedContext) -> None:
    """Ouvre puis clôture les journées de caisse que les versements ont remplies.

    La journée du jour reste ouverte, montants à blanc : c'est l'état réel
    d'une caisse en cours, et c'est la condition pour que le service accepte
    encore un versement pendant la démonstration. Une journée déjà clôturée
    n'est jamais rouverte : l'écart a été constaté et signé ce soir-là.
    """
    per_day = await _cash_by_day(ctx)
    existing = {
        (row.cashier_user_id, row.business_date): row
        for row in (await ctx.db.execute(select(CashSession))).scalars().all()
    }

    for cashier_id, business_day in sorted(per_day):
        session = existing.get((cashier_id, business_day))
        if session is None:
            session = CashSession(
                cashier_user_id=cashier_id,
                business_date=business_day,
                status=CashSessionStatus.OPEN,
                opened_at=datetime.combine(business_day, time(7, 30)),
            )
            ctx.db.add(session)
            ctx.tally("journées de caisse")
        if business_day >= ctx.today or _is_closed(session):
            continue

        expected = per_day[(cashier_id, business_day)]
        variance = _variance(ctx)
        session.status = CashSessionStatus.CLOSED
        session.closed_at = datetime.combine(business_day, time(17, 45))
        session.expected_amount = expected
        session.counted_amount = expected + variance
        session.variance = variance
        session.notes = _variance_note(variance)
        ctx.tally("journées de caisse clôturées")

    await ctx.db.commit()


async def run(ctx: SeedContext) -> None:
    await pay_school_year(ctx)
    await settle_cash_days(ctx)
