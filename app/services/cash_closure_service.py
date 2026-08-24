"""Clôture d'office des journées de caisse oubliées, et régularisation.

Une journée de caisse qu'on laisse ouverte au-delà de minuit empêche la
comptabilité du lendemain de repartir d'une caisse arrêtée. La pratique du
métier n'est pourtant PAS de clôturer automatiquement avec un montant compté :
personne n'a ouvert le tiroir, donc l'écart ne veut rien dire, et faire signer
un caissier sur un chiffre qu'il n'a pas produit est un faux.

Ce module fait donc ce que fait un logiciel de caisse sérieux : une clôture
d'office, distincte d'une clôture normale. La journée est verrouillée, le
théorique est figé exactement comme à la clôture, mais le montant compté reste
vide et l'écart reste inconnu — et non pas zéro. Le caissier est prévenu, et
régularise le lendemain en saisissant ce qu'il a compté ; l'écart naît alors,
contre le théorique figé la veille.

Séparé de `cash_session_service` parce que ce sont deux gestes différents :
là-bas le guichet en temps réel, ici le balayage de nuit et son rattrapage.
"""

import logging
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, audit_log
from app.core.datetimes import utcnow_naive
from app.core.exceptions import NotFoundError
from app.models.cash_session import CashSession, CashSessionStatus
from app.models.notification import Notification, NotificationChannel, NotificationType
from app.repositories import cash_session_repository as repo
from app.schemas.cash_session import CashSessionRegularizeRequest, CashSessionResponse
from app.services.cash_session_service import to_response

logger = logging.getLogger(__name__)

# Nombre maximum de journées traitées par exécution. La migration 0044 a
# reconstitué en `open` toutes les journées historiques des versements
# antérieurs à la caisse : sur une école qui encaisse depuis des mois, la
# première nuit en trouve des centaines. Un lot borné évite une transaction
# géante et un verrou long sur `cash_sessions` ; les exécutions suivantes
# rattrapent le reste, les plus vieilles journées d'abord.
BATCH_LIMIT = 200

# Nombre de dates citées nommément dans la notification. Au-delà, le caissier
# lit un décompte : lui énumérer quarante dates ne l'aide pas à agir.
_MAX_DATES_LISTED = 5


@dataclass(frozen=True, slots=True)
class AutoClosureReport:
    """Ce qu'une exécution du balayage a réellement fait.

    Renvoyé plutôt que journalisé seulement : c'est ce que la tâche Celery
    remonte, et ce sur quoi les tests s'appuient.
    """

    closed: int = 0
    cashiers_notified: int = 0
    # Vrai quand le lot était plein : il reste des journées pour la prochaine
    # exécution. Sans ce drapeau, un rattrapage partiel passerait pour complet.
    has_more: bool = False


def _french_date(day: date_type) -> str:
    """« 20/08/2026 » — le format que les écoles lisent sur leurs pièces."""
    return day.strftime("%d/%m/%Y")


def _enumerate_days(days: list[date_type]) -> str:
    """« 20/08/2026 », « 21/06/2026 et 20/08/2026 », « A, B et 3 autres ».

    Le dernier séparateur est un « et » et non une virgule : la notification
    est lue par le caissier, pas parsée par une machine.
    """
    listed = [_french_date(day) for day in days[:_MAX_DATES_LISTED]]
    remainder = len(days) - len(listed)
    if remainder > 0:
        listed.append(f"{remainder} autre{'s' if remainder > 1 else ''}")
    if len(listed) == 1:
        return listed[0]
    return f"{', '.join(listed[:-1])} et {listed[-1]}"


def _notification_body(days: list[date_type]) -> str:
    """Corps de la notification, accordé au nombre de journées concernées.

    L'accord était fautif au pluriel : « Votre journées de caisse du 21/06,
    20/08 ont été clôturées ». Le possessif et l'article se déclinent avec le
    reste — c'est un message que le caissier voit tous les matins où il a
    oublié de clôturer, et une faute d'accord y est visible longtemps.
    """
    several = len(days) > 1
    return (
        f"{'Vos journées' if several else 'Votre journée'} de caisse "
        f"{'des' if several else 'du'} {_enumerate_days(days)} "
        f"{'ont' if several else 'a'} été clôturée{'s' if several else ''} d'office à minuit, "
        "sans comptage du tiroir. L'écart reste inconnu tant que vous n'avez pas "
        "saisi ce que vous avez compté. Rendez-vous sur « Ma caisse » pour régulariser."
    )


async def auto_close_stale_sessions(
    db: AsyncSession, *, business_date: date_type, limit: int = BATCH_LIMIT
) -> AutoClosureReport:
    """Clôture d'office les journées révolues restées ouvertes.

    `business_date` est la journée de guichet EN COURS, calculée dans le fuseau
    de l'école : seules les journées STRICTEMENT antérieures sont touchées, une
    caisse du jour étant en plein service.

    Idempotente par construction : le filtre porte sur `status == open`, et une
    journée traitée passe en `auto_closed`. La rejouer ne reclôture rien et ne
    touche pas à un écart déjà constaté — ni celui d'une clôture signée, ni
    celui d'une régularisation, qui sont l'un comme l'autre en `closed`.
    """
    sessions = await repo.list_stale_open_sessions(db, before=business_date, limit=limit)
    if not sessions:
        return AutoClosureReport()

    # Un seul agrégat pour tout le lot : une requête par journée rejouerait le
    # N+1 que le point journalier avait déjà supprimé.
    aggregates = await repo.aggregate_days_by_cashier(
        db, [(s.cashier_user_id, s.business_date) for s in sessions]
    )

    closed_at = utcnow_naive()
    days_by_cashier: dict[int, list[date_type]] = {}

    for session in sessions:
        aggregate = aggregates.get((session.cashier_user_id, session.business_date))
        expected = aggregate.cash_total if aggregate is not None else Decimal("0")

        session.status = CashSessionStatus.AUTO_CLOSED
        session.closed_at = closed_at
        # Le théorique est figé comme sur une clôture normale : c'est contre
        # lui que se calculera l'écart le jour de la régularisation.
        session.expected_amount = expected
        # `counted_amount` et `variance` restent volontairement à None.
        # Écrire 0 affirmerait que le tiroir tombait juste ; personne ne l'a
        # ouvert, l'écart est inconnu, et c'est cette inconnue qu'il faut
        # transmettre au comptable.

        await _audit_auto_closure(db, session, expected)
        days_by_cashier.setdefault(session.cashier_user_id, []).append(session.business_date)

    for cashier_user_id, days in days_by_cashier.items():
        db.add(
            Notification(
                user_id=cashier_user_id,
                type=NotificationType.SYSTEM.value,
                channel=NotificationChannel.IN_APP.value,
                title="Journée de caisse clôturée d'office",
                body=_notification_body(days),
                read=False,
                sent_at=closed_at,
                entity_type="cash_session",
                # Une notification par caissier et par exécution, pas une par
                # journée : un rattrapage historique en enverrait quarante
                # d'un coup et la cloche deviendrait illisible.
                entity_id=None,
            )
        )

    await db.commit()
    logger.info("Cash auto-closure: closed=%d cashiers=%d", len(sessions), len(days_by_cashier))
    return AutoClosureReport(
        closed=len(sessions),
        cashiers_notified=len(days_by_cashier),
        has_more=len(sessions) >= limit,
    )


async def _audit_auto_closure(db: AsyncSession, session: CashSession, expected: Decimal) -> None:
    """Trace nominative : une clôture d'office engage, même sans auteur humain.

    `user_id` est nul — c'est le système qui agit, et lui attribuer le compte
    du caissier laisserait croire qu'il a clôturé lui-même. Le caissier
    concerné est nommé dans les valeurs, avec son email, pour qu'on retrouve
    dans dix ans QUI aurait dû compter ce tiroir.
    """
    await audit_log(
        db,
        entity_type="cash_session",
        action=AuditAction.UPDATE,
        user_id=None,
        entity_id=session.id,
        old_values={"status": CashSessionStatus.OPEN.value},
        new_values={
            "status": CashSessionStatus.AUTO_CLOSED.value,
            "business_date": session.business_date.isoformat(),
            "cashier_user_id": session.cashier_user_id,
            "cashier_email": session.cashier.email if session.cashier else None,
            "expected_amount": float(expected),
            "counted_amount": None,
            "variance": None,
        },
        notes=(
            "Clôture d'office à minuit : la journée n'avait pas été clôturée. "
            "Tiroir non compté, écart inconnu."
        ),
    )


async def list_sessions_to_regularize(
    db: AsyncSession, cashier_user_id: int
) -> list[CashSessionResponse]:
    """Journées de ce caissier clôturées d'office et pas encore comptées."""
    sessions = await repo.list_sessions_to_regularize(db, cashier_user_id)
    if not sessions:
        return []
    aggregates = await repo.aggregate_days_by_cashier(
        db, [(s.cashier_user_id, s.business_date) for s in sessions]
    )
    names = await repo.cashier_names(db, [cashier_user_id])
    name = names.get(cashier_user_id, "—")
    return [
        to_response(
            session,
            cashier_name=name,
            aggregate=aggregates.get((session.cashier_user_id, session.business_date)),
        )
        for session in sessions
    ]


async def regularize_my_session(
    db: AsyncSession,
    cashier_user_id: int,
    business_date: date_type,
    data: CashSessionRegularizeRequest,
) -> CashSessionResponse:
    """Saisit après coup ce qui a été compté sur une journée clôturée d'office.

    L'écart naît ici, et il se calcule contre le théorique FIGÉ la nuit de la
    clôture d'office — surtout pas contre un théorique recalculé aujourd'hui,
    qui ferait bouger une base déjà arrêtée par la comptabilité.

    La session repasse en `closed` : elle a désormais un montant compté et un
    écart, comme toute journée clôturée. `regularized_at` garde la mémoire du
    détour.
    """
    session = await repo.get_session(db, cashier_user_id, business_date)
    if session is None:
        raise NotFoundError("CashSession", 0)
    if session.status != CashSessionStatus.AUTO_CLOSED:
        raise HTTPException(
            status_code=409,
            detail=(
                "Seule une journée clôturée d'office se régularise. "
                "Cette journée est ouverte ou déjà comptée."
            ),
        )

    # Le théorique a été figé à la clôture d'office. `or Decimal("0")` couvre
    # une journée sans aucun encaissement en espèces, pas une donnée absente.
    expected = session.expected_amount if session.expected_amount is not None else Decimal("0")
    counted = Decimal(str(data.counted_amount))
    regularized_at = utcnow_naive()

    async with db.begin_nested():
        session.status = CashSessionStatus.CLOSED
        session.counted_amount = counted
        session.variance = counted - expected
        session.regularized_at = regularized_at
        session.notes = data.notes
        await audit_log(
            db,
            entity_type="cash_session",
            action=AuditAction.UPDATE,
            user_id=cashier_user_id,
            entity_id=session.id,
            old_values={
                "status": CashSessionStatus.AUTO_CLOSED.value,
                "counted_amount": None,
                "variance": None,
            },
            new_values={
                "status": CashSessionStatus.CLOSED.value,
                "business_date": business_date.isoformat(),
                "expected_amount": float(expected),
                "counted_amount": float(counted),
                "variance": float(counted - expected),
                "regularized_at": regularized_at.isoformat(),
            },
            notes="Régularisation d'une journée clôturée d'office.",
        )
    await db.commit()

    refreshed = await repo.get_session_by_id(db, session.id)
    if refreshed is None:
        raise NotFoundError("CashSession", session.id)
    aggregate = await repo.aggregate_day(db, cashier_user_id, business_date)
    names = await repo.cashier_names(db, [cashier_user_id])
    return to_response(refreshed, cashier_name=names.get(cashier_user_id, "—"), aggregate=aggregate)
