"""Seed permissions + roles + user_roles for the 4 test users on local tenant.

Idempotent. Run AFTER `seed_test_users.py` to grant the admin/teacher/student/parent
users their corresponding role from ROLE_DEFINITIONS.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.tenants.provisioning import _seed_permissions_and_roles  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EMAIL_TO_ROLE = {
    "admin@klassci.com": "admin",
    "prof@klassci.com": "teacher",
    "eleve@klassci.com": "student",
    "parent.kone@klassci.com": "parent",
}


async def main() -> None:
    tenant = os.getenv("TENANT_ID", "local")
    url = settings.DATABASE_URL.format(tenant=tenant)
    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        logger.info("Seeding permissions + role_permissions on tenant '%s'...", tenant)
        await _seed_permissions_and_roles(db)
        await db.commit()
        logger.info("Permissions/roles seeded.")

        for email, role_name in EMAIL_TO_ROLE.items():
            user_row = await db.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": email},
            )
            user_id = user_row.scalar_one_or_none()
            if user_id is None:
                logger.warning("User %s not found, skipping", email)
                continue

            role_row = await db.execute(
                text("SELECT id FROM roles WHERE name = :name"),
                {"name": role_name},
            )
            role_id = role_row.scalar_one_or_none()
            if role_id is None:
                logger.warning("Role %s not found, skipping %s", role_name, email)
                continue

            await db.execute(
                text(
                    "INSERT IGNORE INTO user_roles (user_id, role_id) "
                    "VALUES (:user_id, :role_id)"
                ),
                {"user_id": user_id, "role_id": role_id},
            )
            logger.info("Linked %s -> role '%s' (user_id=%s, role_id=%s)",
                        email, role_name, user_id, role_id)

        await db.commit()

    await engine.dispose()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
