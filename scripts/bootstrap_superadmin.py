"""Bootstrap the system tenant `local` and the platform superadmin.

Idempotent. Used on first production boot after MySQL is healthy.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.services.tenants.permissions import ROLE_DEFINITIONS
from app.services.tenants.provisioning import (
    _seed_permissions_and_roles,
    create_tenant_database,
    run_migrations,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TENANT = os.getenv("TENANT_ID", "local")
EMAIL = os.getenv("SUPERADMIN_EMAIL", "superadmin@klassci.com")
PASSWORD = os.getenv("SUPERADMIN_PASSWORD")


async def _ensure_superadmin(url: str) -> None:
    if not PASSWORD:
        raise RuntimeError("SUPERADMIN_PASSWORD is required")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        async with db.begin():
            await _seed_permissions_and_roles(db)
            role_row = await db.execute(text("SELECT id FROM roles WHERE name = 'super_admin'"))
            role_id = role_row.scalar_one()
            existing = await db.execute(text("SELECT id FROM users WHERE email = :email"), {"email": EMAIL})
            user_id = existing.scalar_one_or_none()
            hashed = hash_password(PASSWORD)
            if user_id is None:
                inserted = await db.execute(
                    text(
                        "INSERT INTO users (email, hashed_password, role, is_active, must_change_password) "
                        "VALUES (:email, :hashed, 'super_admin', 1, 0)"
                    ),
                    {"email": EMAIL, "hashed": hashed},
                )
                user_id = int(inserted.lastrowid)
                logger.info("Created superadmin %s", EMAIL)
            else:
                await db.execute(
                    text(
                        "UPDATE users SET role = 'super_admin', is_active = 1, "
                        "must_change_password = 0, hashed_password = :hashed WHERE id = :id"
                    ),
                    {"hashed": hashed, "id": user_id},
                )
                logger.info("Reset superadmin %s", EMAIL)
            await db.execute(
                text(
                    "INSERT INTO user_roles (user_id, role_id) "
                    "SELECT :user_id, :role_id WHERE NOT EXISTS ("
                    "SELECT 1 FROM user_roles WHERE user_id = :user_id AND role_id = :role_id)"
                ),
                {"user_id": user_id, "role_id": role_id},
            )
            if "super_admin" not in ROLE_DEFINITIONS:
                logger.warning("super_admin missing from ROLE_DEFINITIONS")
    await engine.dispose()


async def main() -> None:
    from app.core.config import settings

    await create_tenant_database(TENANT)
    await run_migrations(TENANT)
    await _ensure_superadmin(settings.DATABASE_URL.format(tenant=TENANT))


if __name__ == "__main__":
    asyncio.run(main())
