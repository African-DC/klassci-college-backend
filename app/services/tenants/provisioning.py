"""Tenant provisioning workflow — create DB → migrate → seed → welcome email.

Idempotent on the user existence check: re-running for a tenant whose admin
already exists raises `TenantAlreadyProvisioned` instead of silently
overwriting credentials or duplicating staff_profiles / school_settings.

Subprocess-based alembic call inherited from the original implementation. A
follow-up task (see operations layer) may swap to a programmatic alembic
runner once the CLI matures, but subprocess is robust enough for now and
isolates env var leakage.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import hash_password
from app.services.tenants.exceptions import TenantAlreadyProvisioned
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$")


async def create_tenant_database(tenant_slug: str) -> None:
    """Step 1: create the MySQL database for the tenant (idempotent)."""
    base_url = settings.DATABASE_URL.replace("/{tenant}", "/")
    mgmt_engine = create_async_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        async with mgmt_engine.begin() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{tenant_slug}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            logger.info("Database '%s' created", tenant_slug)
    finally:
        await mgmt_engine.dispose()


async def run_migrations(tenant_slug: str) -> None:
    """Step 2: run all Alembic migrations on the tenant database."""
    env = os.environ.copy()
    env["TENANT_ID"] = tenant_slug
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parents[3]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed for tenant '{tenant_slug}': {result.stderr}")
    logger.info("Migrations applied for tenant '%s'", tenant_slug)


async def _seed_permissions_and_roles(db: AsyncSession) -> None:
    for perm in ALL_PERMISSIONS:
        await db.execute(
            text("INSERT IGNORE INTO permissions (slug, name) VALUES (:slug, :name)"),
            perm,
        )

    for role_name, role_def in ROLE_DEFINITIONS.items():
        await db.execute(
            text("INSERT IGNORE INTO roles (name, description) VALUES (:name, :desc)"),
            {"name": role_name, "desc": role_def["description"]},
        )
        result = await db.execute(
            text("SELECT id FROM roles WHERE name = :name"),
            {"name": role_name},
        )
        role_id = result.scalar_one()

        for slug in role_def["permissions"]:
            await db.execute(
                text(
                    "INSERT IGNORE INTO role_permissions (role_id, permission_id) "
                    "SELECT :role_id, id FROM permissions WHERE slug = :slug"
                ),
                {"role_id": role_id, "slug": slug},
            )


async def _create_admin_user(
    db: AsyncSession,
    *,
    tenant_slug: str,
    admin_email: str,
    admin_password: str,
    school_name: str,
) -> int:
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": admin_email},
    )
    existing_id = existing.scalar_one_or_none()
    if existing_id is not None:
        raise TenantAlreadyProvisioned(
            tenant_slug=tenant_slug,
            admin_email=admin_email,
            existing_user_id=existing_id,
        )

    await db.execute(
        text(
            "INSERT INTO users (email, hashed_password, role, is_active) "
            "VALUES (:email, :hashed, 'admin', 1)"
        ),
        {"email": admin_email, "hashed": hash_password(admin_password)},
    )
    inserted = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": admin_email},
    )
    admin_user_id = inserted.scalar_one()

    role_lookup = await db.execute(text("SELECT id FROM roles WHERE name = 'admin'"))
    admin_role_id = role_lookup.scalar_one()
    await db.execute(
        text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
        {"user_id": admin_user_id, "role_id": admin_role_id},
    )

    await db.execute(
        text(
            "INSERT INTO staff_profiles (user_id, first_name, last_name, position) "
            "VALUES (:user_id, 'Admin', :school_name, 'Administrateur')"
        ),
        {"user_id": admin_user_id, "school_name": school_name},
    )
    return admin_user_id


async def _seed_school_settings(
    db: AsyncSession,
    *,
    school_name: str,
    school_address: str | None,
    school_phone: str | None,
    school_email: str | None,
    ministry_code: str | None,
) -> None:
    existing = await db.execute(text("SELECT id FROM school_settings LIMIT 1"))
    if existing.scalar_one_or_none() is not None:
        return
    await db.execute(
        text(
            "INSERT INTO school_settings "
            "(school_name, address, phone, email, ministry_code) "
            "VALUES (:name, :address, :phone, :email, :code)"
        ),
        {
            "name": school_name,
            "address": school_address,
            "phone": school_phone,
            "email": school_email,
            "code": ministry_code,
        },
    )


async def seed_tenant_data(
    tenant_slug: str,
    *,
    school_name: str,
    admin_email: str,
    admin_password: str,
    school_address: str | None = None,
    school_phone: str | None = None,
    school_email: str | None = None,
    ministry_code: str | None = None,
) -> dict[str, Any]:
    """Step 3: seed permissions, roles, admin user, and school settings."""
    tenant_url = settings.DATABASE_URL.format(tenant=tenant_slug)
    engine = create_async_engine(tenant_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as db:
            async with db.begin():
                await _seed_permissions_and_roles(db)
                admin_user_id = await _create_admin_user(
                    db,
                    tenant_slug=tenant_slug,
                    admin_email=admin_email,
                    admin_password=admin_password,
                    school_name=school_name,
                )
                await _seed_school_settings(
                    db,
                    school_name=school_name,
                    school_address=school_address,
                    school_phone=school_phone,
                    school_email=school_email,
                    ministry_code=ministry_code,
                )
            logger.info("Seed data inserted for tenant '%s'", tenant_slug)
            return {"admin_user_id": admin_user_id, "admin_email": admin_email}
    finally:
        await engine.dispose()


async def provision_tenant(
    *,
    tenant_slug: str,
    school_name: str,
    admin_email: str,
    admin_password: str,
    admin_first_name: str = "",
    school_address: str | None = None,
    school_phone: str | None = None,
    school_email: str | None = None,
    ministry_code: str | None = None,
    send_welcome_email: bool = True,
) -> dict[str, Any]:
    """Full provisioning workflow: create DB → migrate → seed → welcome email."""
    if not _SLUG_RE.match(tenant_slug):
        raise ValueError(
            f"Invalid tenant_slug '{tenant_slug}': "
            "must be 2-63 chars, lowercase alphanumeric + hyphens"
        )

    logger.info("=== Provisioning tenant '%s' ===", tenant_slug)

    await create_tenant_database(tenant_slug)
    await run_migrations(tenant_slug)
    seed_result = await seed_tenant_data(
        tenant_slug,
        school_name=school_name,
        admin_email=admin_email,
        admin_password=admin_password,
        school_address=school_address,
        school_phone=school_phone,
        school_email=school_email,
        ministry_code=ministry_code,
    )

    email_sent = False
    if send_welcome_email:
        from app.services.email_service import send_tenant_welcome

        email_sent = send_tenant_welcome(
            admin_email=admin_email,
            admin_first_name=admin_first_name,
            school_name=school_name,
            tenant_slug=tenant_slug,
            temp_password=admin_password,
        )
        if not email_sent:
            logger.warning("Welcome email not sent to %s — vérifier config SMTP", admin_email)

    logger.info("=== Tenant '%s' provisioned successfully ===", tenant_slug)
    return {
        "tenant_slug": tenant_slug,
        "database": tenant_slug,
        "admin_email": seed_result["admin_email"],
        "tenant_url": f"https://{tenant_slug}.college.klassci.com",
        "welcome_email_sent": email_sent,
        "status": "provisioned",
    }
