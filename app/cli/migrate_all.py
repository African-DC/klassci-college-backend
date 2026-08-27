"""CLI — Migrer toutes les bases de données tenant.

Usage:
    python -m app.cli.migrate_all [revision]
    python -m app.cli.migrate_all head
"""

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

#: Delai par base. Deux minutes suffisaient tant qu'aucune migration ne
#: touchait aux donnees ; une migration qui remplit une colonne sur un gros
#: fichier eleves peut les depasser, et un depassement est pire qu'une
#: attente : il coupe alembic au milieu.
_DELAI_PAR_TENANT = 900


async def list_tenant_databases() -> list[str]:
    """List databases carrying the KLASSCI tenant schema markers."""
    from app.core.config import settings

    base_url = settings.DATABASE_URL.replace("/{tenant}", "/")
    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT table_schema
                    FROM information_schema.tables
                    WHERE table_name IN (
                        'alembic_version', 'users', 'roles', 'academic_years'
                    )
                    AND table_schema REGEXP '^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$'
                    GROUP BY table_schema
                    HAVING COUNT(DISTINCT table_name) = 4
                    ORDER BY table_schema
                    """
                )
            )
            all_dbs = [row[0] for row in result.fetchall()]
    finally:
        await engine.dispose()

    return all_dbs


async def migrate_all(revision: str = "head") -> None:
    """Run Alembic migrations on all tenant databases."""
    tenants = await list_tenant_databases()
    logger.info("Found %d tenant databases", len(tenants))
    if not tenants:
        raise RuntimeError("No KLASSCI tenant database found; refusing to deploy")

    from app.core.config import settings

    if (
        settings.APP_ENV.lower() in {"production", "prod"}
        and settings.LOCAL_TENANT_ID not in tenants
    ):
        raise RuntimeError("Production tenant 'local' is missing; refusing to deploy")

    project_root = str(Path(__file__).resolve().parents[2])
    failed: list[tuple[str, str]] = []

    for tenant in tenants:
        logger.info("Migrating '%s'...", tenant)
        env = os.environ.copy()
        env["TENANT_ID"] = tenant
        try:
            result = subprocess.run(
                ["alembic", "upgrade", revision],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=_DELAI_PAR_TENANT,
            )
        except subprocess.TimeoutExpired:
            # Le depassement TUE alembic en pleine migration, ce qui laisse la
            # base dans l'etat partiel dont on ne sort qu'a la main. On ne peut
            # pas l'empecher ici, mais on peut le dire fort et continuer les
            # autres tenants au lieu de remonter une exception nue.
            message = (
                f"delai de {_DELAI_PAR_TENANT}s depasse : alembic a ete interrompu EN COURS "
                "de migration, cette base est probablement dans un etat partiel"
            )
            failed.append((tenant, message))
            logger.error("  %s", message)
            continue
        if result.returncode != 0:
            failed.append((tenant, result.stderr[:200]))
            logger.error("  Failed: %s", result.stderr[:200])
        else:
            logger.info("  OK")

    if failed:
        logger.error("%d tenants failed:", len(failed))
        for name, err in failed:
            logger.error("  - %s: %s", name, err)
        sys.exit(1)
    else:
        logger.info("All %d tenants migrated successfully", len(tenants))


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrer toutes les bases tenant")
    parser.add_argument(
        "revision", nargs="?", default="head", help="Revision Alembic (default: head)"
    )
    args = parser.parse_args()
    asyncio.run(migrate_all(args.revision))


if __name__ == "__main__":
    main()
