"""Moteur SQLAlchemy async + gestion des sessions par tenant."""

from collections.abc import AsyncGenerator
from contextvars import ContextVar
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# ContextVar qui stocke le tenant_id courant pour chaque requête
current_tenant_id: ContextVar[str] = ContextVar("current_tenant_id", default=settings.LOCAL_TENANT_ID)


class Base(DeclarativeBase):
    """Base commune pour tous les modèles SQLAlchemy."""
    pass


@lru_cache(maxsize=64)
def _get_session_factory(tenant_id: str) -> async_sessionmaker[AsyncSession]:
    """Retourne (ou crée) la session factory scopée sur le tenant.

    L'engine est créé une seule fois par tenant grâce au cache LRU.
    Le pool de connexions est ainsi réutilisé entre les requêtes.
    """
    engine = create_async_engine(
        settings.DATABASE_URL.format(tenant=tenant_id),
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=settings.DEBUG,
    )
    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency FastAPI — retourne une session pour le tenant courant."""
    tenant_id = current_tenant_id.get()
    factory = _get_session_factory(tenant_id)
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
