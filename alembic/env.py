"""Alembic env.py — mode async avec SQLAlchemy 2.0."""

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

# Import de tous les modèles pour que leurs tables soient connues de Base.metadata
import app.models  # noqa: F401 — enregistre toutes les tables via __init__.py
from alembic import context
from app.core.config import settings
from app.core.database import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url(tenant_id: str = "alembic_migration") -> str:
    """Retourne l'URL de connexion pour le tenant donné.

    En migration, le tenant est passé via la variable d'env TENANT_ID
    ou vaut "alembic_migration" par défaut (utilisé en CI pour dry-run).
    """
    import os

    tenant = os.getenv("TENANT_ID", tenant_id)
    return settings.DATABASE_URL.format(tenant=tenant)


def run_migrations_offline() -> None:
    """Mode hors-ligne : génère le SQL sans connexion active."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Mode en ligne : connexion async et exécution des migrations."""
    connectable = create_async_engine(_get_url(), echo=False)
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda conn: context.configure(
                connection=conn,
                target_metadata=target_metadata,
                compare_type=True,
            )
        )
        async with connection.begin():
            await connection.run_sync(lambda conn: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
