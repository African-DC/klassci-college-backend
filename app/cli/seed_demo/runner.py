"""L'orchestrateur : quelles étapes, dans quel ordre, et pourquoi cet ordre.

L'ordre n'est pas un goût, c'est une chaîne de dépendances :

1. le **référentiel** doit exister avant tout, et l'année doit être marquée
   courante, sinon la moitié des services refuse de travailler ;
2. les **enseignants** avant les matières, parce qu'une instance de matière
   porte son titulaire, et qu'une matière sans titulaire ne peut recevoir ni
   évaluation ni créneau ;
3. la **grille tarifaire** avant les inscriptions, parce que c'est l'inscription
   qui transforme un tarif en dette ;
4. l'**emploi du temps** avant les présences enseignants, qui pointent des
   créneaux, et avant le rapport officiel, qui déduit de lui la répartition par
   discipline ;
5. les **notes** et les **présences** avant la vie scolaire, dont les billets
   d'annulation de zéro visent de vraies absences et de vrais zéros.

Chaque étape est indépendante et relançable seule (`--only`), ce qui permet de
reprendre après un incident sans refaire les six cents élèves.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cli.seed_demo import (
    academics,
    billing,
    cashdesk,
    curriculum,
    deep_data,
    extras,
    families,
    presence,
    referentiel,
    schoollife,
    staffing,
    timetabling,
)
from app.cli.seed_demo.context import SeedContext, logger
from app.cli.seed_demo.report import figures, render
from app.core.audit import Actor, current_actor
from app.core.database import current_tenant_id
from app.models.user import User, UserRoleEnum

Step = tuple[str, Callable[[SeedContext], Awaitable[None]]]

#: Les étapes, dans l'ordre imposé par les dépendances ci-dessus.
STEPS: tuple[Step, ...] = (
    ("referentiel", referentiel.run),
    ("staffing", staffing.run),
    ("curriculum", curriculum.run),
    ("billing", billing.run),
    ("families", families.run),
    ("timetabling", timetabling.run),
    ("academics", academics.run),
    ("cashdesk", cashdesk.run),
    ("presence", presence.run),
    ("schoollife", schoollife.run),
    ("deep_data", deep_data.run),
    ("extras", extras.run),
)

STEP_NAMES: tuple[str, ...] = tuple(name for name, _run in STEPS)


async def _resolve_actor(db: AsyncSession) -> tuple[int, str]:
    """Le compte qui signera les écritures du semis.

    On prend un administrateur existant plutôt que d'en fabriquer un : le
    journal d'audit doit désigner quelqu'un que l'établissement reconnaît, et
    un « compte de semis » apparaissant partout dans l'historique serait le
    premier détail qu'un client remarquerait.
    """
    statement = (
        select(User.id, User.email)
        .where(User.role == UserRoleEnum.ADMIN.value, User.is_active.is_(True))
        .order_by(User.id)
        .limit(1)
    )
    row = (await db.execute(statement)).first()
    if row is None:
        raise RuntimeError(
            "Aucun compte administrateur actif sur ce locataire. "
            "Provisionnez le tenant avant de semer les données de démonstration."
        )
    return int(row[0]), str(row[1])


async def seed(tenant: str, *, only: tuple[str, ...] = ()) -> dict[str, object]:
    """Sème le locataire et retourne les chiffres relus en base."""
    from app.core.config import settings

    # Le ContextVar de tenant est lu par les services qui scellent un document :
    # sans lui, un cachet de démonstration porterait le mauvais établissement.
    tenant_token = current_tenant_id.set(tenant)
    engine = create_async_engine(settings.DATABASE_URL.format(tenant=tenant), pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with factory() as db:
            actor_id, actor_email = await _resolve_actor(db)
            actor_token = current_actor.set(
                Actor(user_id=actor_id, email=actor_email, role="admin")
            )
            ctx = SeedContext(db=db, tenant=tenant, today=date.today(), actor_id=actor_id)

            try:
                await _run_steps(ctx, only)
                values = await figures(ctx)
            finally:
                current_actor.reset(actor_token)

            _log_summary(ctx, values)
            return values
    finally:
        current_tenant_id.reset(tenant_token)
        await engine.dispose()


async def _run_steps(ctx: SeedContext, only: tuple[str, ...]) -> None:
    """Déroule les étapes retenues, en chronométrant chacune.

    Le référentiel tourne toujours, même quand on relance une seule étape : il
    est ce qui remplit les identifiants que les autres consomment, et le sauter
    ferait échouer la reprise sur un dictionnaire vide.
    """
    for name, step in STEPS:
        if only and name not in only and name != "referentiel":
            continue
        started = time.monotonic()
        logger.info("→ %s", name)
        ctx.reseed(name)
        await step(ctx)
        logger.info("  %s terminé en %.1f s", name, time.monotonic() - started)


def _log_summary(ctx: SeedContext, values: dict[str, object]) -> None:
    written = "\n".join(f"  {label:38s} : {count}" for label, count in sorted(ctx.counts.items()))
    logger.info("Écrit par cette exécution :\n%s", written or "  (rien de neuf)")
    logger.info("État du locataire « %s » :\n%s", ctx.tenant, render(values))
