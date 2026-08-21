"""Tâches Celery — clôture d'office des journées de caisse à minuit.

Deux tâches distinctes, parce que ce sont deux responsabilités : l'une balaie
la liste des établissements, l'autre traite un établissement. C'est
l'ordonnanceur (`beat_schedule`) qui déclenche la première ; la seconde reste
appelable seule, pour rattraper une école en particulier sans toucher aux
autres.

`audit_tasks.purge_read_entries_task` prend déjà un `tenant_id` en paramètre
mais n'énumère PAS les établissements : personne ne l'appelle en boucle, et
aucun `beat_schedule` ne la déclenche. Le balayage multi-établissement est
donc écrit ici, à partir de `list_tenant_slugs()`, seule source qui connaisse
les bases existantes.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.celery_app import celery_app
from app.core.database import current_tenant_id, tenant_database_url
from app.core.datetimes import current_business_date
from app.services.cash_closure_service import auto_close_stale_sessions
from app.services.tenants.query import list_tenant_slugs

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="cash.close_stale_sessions_all_tenants")  # type: ignore[misc]
def close_stale_cash_sessions_all_tenants_task(self: Any) -> dict[str, Any]:
    """Balaie TOUS les établissements. Déclenchée par l'ordonnanceur à minuit.

    Un établissement en échec ne doit pas priver les autres de leur clôture :
    l'exception est journalisée et le balayage continue. Le compte des échecs
    remonte dans le résultat pour qu'un silence ne passe pas pour un succès.
    """
    slugs = asyncio.run(list_tenant_slugs())
    totals = {"tenants": len(slugs), "closed": 0, "failed": 0, "pending": 0}

    for slug in slugs:
        try:
            report = asyncio.run(_close_stale_async(slug))
        except Exception:
            logger.exception("Cash auto-closure failed for tenant=%s", slug)
            totals["failed"] += 1
            continue
        totals["closed"] += report["closed"]
        totals["pending"] += 1 if report["has_more"] else 0

    logger.info("Cash auto-closure sweep: %s", totals)
    return totals


@celery_app.task(bind=True, name="cash.close_stale_sessions")  # type: ignore[misc]
def close_stale_cash_sessions_task(self: Any, tenant_id: str) -> dict[str, Any]:
    """Clôture d'office les journées révolues d'UN établissement."""
    try:
        return asyncio.run(_close_stale_async(tenant_id))
    except Exception:
        logger.exception("Cash auto-closure failed for tenant=%s", tenant_id)
        raise


async def _close_stale_async(tenant_id: str) -> dict[str, Any]:
    """Corps async — une connexion courte, refermée quoi qu'il arrive."""
    current_tenant_id.set(tenant_id)
    engine = create_async_engine(tenant_database_url(tenant_id), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as db:
            # La journée EN COURS est calculée dans le fuseau de l'école, pas
            # dans celui du serveur : c'est elle qui définit ce qui est
            # « révolu ». Voir `SCHOOL_TIMEZONE`.
            report = await auto_close_stale_sessions(db, business_date=current_business_date())
    finally:
        await engine.dispose()
    return {
        "tenant": tenant_id,
        "closed": report.closed,
        "cashiers_notified": report.cashiers_notified,
        "has_more": report.has_more,
    }
