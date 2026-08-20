"""Tache Celery — purge des consultations du journal d'audit.

Une consultation est volumineuse par nature : ouvrir vingt dossiers d'eleves
dans une matinee laisse vingt lignes, tous les jours, pour chaque personne du
secretariat. Au bout d'un an la table devient trop lourde pour la page qui la
lit, et le journal cesse d'etre consultable au moment precis ou on en a besoin.

Les consultations sont donc effacees au-dela de six mois. Les creations,
modifications et suppressions, elles, ne sont jamais purgees : ce sont elles
qui portent la responsabilite, et leur volume reste celui des actes reels.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import AuditAction, AuditLog
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.datetimes import utcnow_naive

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=182)  # six mois


@celery_app.task(bind=True, name="audit.purge_reads")  # type: ignore[misc]
def purge_read_entries_task(self: Any, tenant_id: str) -> dict[str, int]:
    """Efface les consultations de plus de six mois pour un etablissement."""
    try:
        deleted = asyncio.run(_purge_async(tenant_id))
    except Exception:
        logger.exception("Audit read purge failed for tenant=%s", tenant_id)
        raise
    logger.info("Audit read purge: tenant=%s deleted=%s", tenant_id, deleted)
    return {"deleted": deleted}


async def _purge_async(tenant_id: str) -> int:
    current_tenant_id.set(tenant_id)
    engine = create_async_engine(settings.DATABASE_URL.format(tenant=tenant_id), echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    cutoff = utcnow_naive() - RETENTION
    try:
        async with factory() as db:
            result = await db.execute(
                delete(AuditLog).where(
                    AuditLog.action == AuditAction.READ,
                    AuditLog.created_at < cutoff,
                )
            )
            await db.commit()
            return int(result.rowcount or 0)
    finally:
        await engine.dispose()
