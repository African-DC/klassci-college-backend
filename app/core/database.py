"""Moteur SQLAlchemy async + gestion des sessions par tenant."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_DATABASES: frozenset[str] = frozenset(
    {"information_schema", "mysql", "performance_schema", "sys", "alembic_migration"}
)


def management_database_url() -> str:
    """URL pour les requêtes cross-tenant (information_schema, CREATE DATABASE)."""
    return settings.DATABASE_URL.replace("/{tenant}", "/")


def tenant_database_url(tenant_slug: str) -> str:
    """URL d'un tenant spécifique — utiliser hors du flow get_db() scopé JWT."""
    return settings.DATABASE_URL.format(tenant=tenant_slug)


# ContextVar qui stocke le tenant_id courant pour chaque requête
current_tenant_id: ContextVar[str] = ContextVar(
    "current_tenant_id", default=settings.LOCAL_TENANT_ID
)

# Registre des engines actifs — dict ordonné (Python 3.7+ : insertion order = FIFO éviction)
# Clé : tenant_id, valeur : (engine, session_factory)
_ENGINE_REGISTRY: dict[str, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]] = {}
_MAX_ENGINES = 64
_REGISTRY_LOCK = asyncio.Lock()


class Base(DeclarativeBase):
    """Base commune pour tous les modèles SQLAlchemy."""

    pass


async def _get_session_factory(tenant_id: str) -> async_sessionmaker[AsyncSession]:
    """Retourne (ou crée) la session factory scopée sur le tenant.

    Maintient un registre d'au plus _MAX_ENGINES engines actifs. Quand la
    limite est atteinte, l'engine le plus ancien (FIFO) est éjecté et
    dispose()d pour libérer proprement toutes ses connexions MySQL.

    Le double-check locking évite les race conditions : deux coroutines
    concurrent sur le même nouveau tenant ne créeront qu'un seul engine.
    """
    # Fast path sans lock — O(1), aucune contention pour les tenants connus
    if tenant_id in _ENGINE_REGISTRY:
        return _ENGINE_REGISTRY[tenant_id][1]

    async with _REGISTRY_LOCK:
        # Double-check : une autre coroutine a peut-être créé l'engine
        # pendant qu'on attendait le lock
        if tenant_id in _ENGINE_REGISTRY:
            return _ENGINE_REGISTRY[tenant_id][1]

        if len(_ENGINE_REGISTRY) >= _MAX_ENGINES:
            oldest_key, (old_engine, _) = next(iter(_ENGINE_REGISTRY.items()))
            del _ENGINE_REGISTRY[oldest_key]
            logger.warning(
                "Engine evicted for tenant '%s' (registry at capacity: %d)",
                oldest_key,
                _MAX_ENGINES,
            )
            try:
                await old_engine.dispose()
            except Exception:
                logger.exception("Failed to dispose evicted engine for tenant '%s'", oldest_key)

        engine = create_async_engine(
            settings.DATABASE_URL.format(tenant=tenant_id),
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=settings.DEBUG,
        )
        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        _ENGINE_REGISTRY[tenant_id] = (engine, factory)
        return factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency FastAPI — retourne une session pour le tenant courant."""
    tenant_id = current_tenant_id.get()
    factory = await _get_session_factory(tenant_id)
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
