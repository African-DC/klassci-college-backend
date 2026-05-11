"""Tenant provisioning workflow — create DB → migrate → seed → welcome email.

Idempotent on the user existence check: re-running for a tenant whose admin
already exists raises `TenantAlreadyProvisioned` instead of silently
overwriting credentials or duplicating staff_profiles / school_settings.

Subprocess-based alembic call (rather than programmatic) isolates env-var
leakage between concurrent provisioning calls.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import management_database_url, tenant_database_url
from app.core.security import hash_password
from app.core.slug import validate_new_tenant_slug, validate_tenant_slug
from app.models.user import UserRoleEnum
from app.services.tenants._engine import short_lived_engine
from app.services.tenants.exceptions import TenantAlreadyProvisioned
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS

logger = logging.getLogger(__name__)


async def create_tenant_database(tenant_slug: str) -> None:
    """Step 1: create the MySQL database for the tenant (idempotent).

    Re-validates the slug at the boundary even though callers (provision_tenant
    and the BE-7 operations layer) are expected to have already done so. The
    slug ends up in raw SQL via f-string because MySQL ``CREATE DATABASE``
    does not accept parameter binding for the database name — defense in
    depth via strict regex is the only available control.
    """
    validate_tenant_slug(tenant_slug)
    async with short_lived_engine(
        management_database_url(), isolation_level="AUTOCOMMIT"
    ) as engine:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{tenant_slug}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
            logger.info("Database '%s' created", tenant_slug)


async def run_migrations(tenant_slug: str) -> None:
    """Step 2: run all Alembic migrations on the tenant database."""
    validate_tenant_slug(tenant_slug)
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


async def create_admin_user_for_tenant(
    db: AsyncSession,
    *,
    tenant_slug: str,
    admin_email: str,
    admin_password: str,
    school_name: str,
) -> int:
    """Insert admin User + UserRole + StaffProfile, or raise if already exists."""
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

    insert_user = await db.execute(
        text(
            "INSERT INTO users (email, hashed_password, role, is_active) "
            "VALUES (:email, :hashed, :role, 1)"
        ),
        {
            "email": admin_email,
            "hashed": hash_password(admin_password),
            "role": UserRoleEnum.ADMIN.value,
        },
    )
    admin_user_id = int(insert_user.lastrowid)

    role_lookup = await db.execute(
        text("SELECT id FROM roles WHERE name = :name"),
        {"name": UserRoleEnum.ADMIN.value},
    )
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
    validate_tenant_slug(tenant_slug)
    async with short_lived_engine(tenant_database_url(tenant_slug), pool_pre_ping=True) as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as db:
            async with db.begin():
                await _seed_permissions_and_roles(db)
                admin_user_id = await create_admin_user_for_tenant(
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
    validate_new_tenant_slug(tenant_slug)

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

    login_url = settings.PUBLIC_LOGIN_URL_TEMPLATE.format(slug=tenant_slug)

    email_sent = False
    if send_welcome_email:
        from app.services.email_service import send_tenant_welcome

        email_sent = send_tenant_welcome(
            admin_email=admin_email,
            admin_first_name=admin_first_name,
            school_name=school_name,
            login_url=login_url,
            temp_password=admin_password,
        )
        if not email_sent:
            logger.warning("Welcome email not sent to %s — vérifier config SMTP", admin_email)

    logger.info("=== Tenant '%s' provisioned successfully ===", tenant_slug)
    return {
        "tenant_slug": tenant_slug,
        "database": tenant_slug,
        "admin_email": seed_result["admin_email"],
        "tenant_url": login_url,
        "welcome_email_sent": email_sent,
        "status": "provisioned",
    }
