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


async def list_tenant_databases() -> list[str]:
    """List all tenant databases (convention: exclude system DBs)."""
    from app.core.config import settings

    base_url = settings.DATABASE_URL.replace("/{tenant}", "/")
    engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("SHOW DATABASES"))
            all_dbs = [row[0] for row in result.fetchall()]
    finally:
        await engine.dispose()

    # Exclude MySQL system databases
    system_dbs = {"information_schema", "mysql", "performance_schema", "sys", "alembic_migration"}
    return [db for db in all_dbs if db not in system_dbs]


async def migrate_all(revision: str = "head") -> None:
    """Run Alembic migrations on all tenant databases."""
    tenants = await list_tenant_databases()
    logger.info("Found %d tenant databases", len(tenants))

    project_root = str(Path(__file__).resolve().parents[2])
    failed: list[tuple[str, str]] = []

    for tenant in tenants:
        logger.info("Migrating '%s'...", tenant)
        env = os.environ.copy()
        env["TENANT_ID"] = tenant
        result = subprocess.run(
            ["alembic", "upgrade", revision],
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
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
