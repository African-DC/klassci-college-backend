"""Service de provisioning multi-tenant — crée une DB, migre, et seed les données initiales."""

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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 46 permission slugs (extracted from all routers)
# ---------------------------------------------------------------------------

ALL_PERMISSIONS: list[dict[str, str]] = [
    # Admin module (28)
    {"slug": "admin:students:read", "name": "View students"},
    {"slug": "admin:students:create", "name": "Create students"},
    {"slug": "admin:students:update", "name": "Update students"},
    {"slug": "admin:students:delete", "name": "Delete students"},
    {"slug": "admin:teachers:read", "name": "View teachers"},
    {"slug": "admin:teachers:create", "name": "Create teachers"},
    {"slug": "admin:teachers:update", "name": "Update teachers"},
    {"slug": "admin:teachers:delete", "name": "Delete teachers"},
    {"slug": "admin:staff:read", "name": "View staff"},
    {"slug": "admin:staff:create", "name": "Create staff"},
    {"slug": "admin:staff:update", "name": "Update staff"},
    {"slug": "admin:staff:delete", "name": "Delete staff"},
    {"slug": "admin:classes:read", "name": "View classes"},
    {"slug": "admin:classes:create", "name": "Create classes"},
    {"slug": "admin:classes:update", "name": "Update classes"},
    {"slug": "admin:classes:delete", "name": "Delete classes"},
    {"slug": "admin:subjects:read", "name": "View subjects"},
    {"slug": "admin:subjects:create", "name": "Create subjects"},
    {"slug": "admin:subjects:update", "name": "Update subjects"},
    {"slug": "admin:subjects:delete", "name": "Delete subjects"},
    {"slug": "admin:academic-years:read", "name": "View academic years"},
    {"slug": "admin:academic-years:create", "name": "Create academic years"},
    {"slug": "admin:academic-years:update", "name": "Update academic years"},
    {"slug": "admin:academic-years:delete", "name": "Delete academic years"},
    {"slug": "admin:levels:read", "name": "View levels"},
    {"slug": "admin:levels:create", "name": "Create levels"},
    {"slug": "admin:levels:update", "name": "Update levels"},
    {"slug": "admin:levels:delete", "name": "Delete levels"},
    {"slug": "admin:fee-categories:read", "name": "View fee categories"},
    {"slug": "admin:fee-categories:create", "name": "Create fee categories"},
    {"slug": "admin:fee-categories:update", "name": "Update fee categories"},
    {"slug": "admin:fee-categories:delete", "name": "Delete fee categories"},
    {"slug": "admin:fee-variants:read", "name": "View fee variants"},
    {"slug": "admin:fee-variants:create", "name": "Create fee variants"},
    {"slug": "admin:fee-variants:update", "name": "Update fee variants"},
    {"slug": "admin:fee-variants:delete", "name": "Delete fee variants"},
    {"slug": "admin:fee-options:read", "name": "View fee options"},
    {"slug": "admin:fee-options:create", "name": "Create fee options"},
    {"slug": "admin:fee-options:update", "name": "Update fee options"},
    {"slug": "admin:fee-options:delete", "name": "Delete fee options"},
    # Academic (8)
    {"slug": "enrollments:read", "name": "View enrollments"},
    {"slug": "enrollments:create", "name": "Create enrollments"},
    {"slug": "enrollments:update", "name": "Update enrollments"},
    {"slug": "enrollments:delete", "name": "Delete enrollments"},
    {"slug": "enrollments:promote", "name": "Mass-promote enrollments year over year"},
    {"slug": "grades:read", "name": "View grades"},
    {"slug": "grades:write", "name": "Write grades"},
    {"slug": "bulletins:generate", "name": "Generate bulletins"},
    # Timetable (3)
    {"slug": "timetable:read", "name": "View timetable"},
    {"slug": "timetable:write", "name": "Edit timetable"},
    {"slug": "timetable:generate", "name": "Generate timetable"},
    # Operations (5)
    {"slug": "payments:read", "name": "View payments"},
    {"slug": "payments:create", "name": "Create payments"},
    {"slug": "attendance:read", "name": "View attendance"},
    {"slug": "attendance:create", "name": "Create attendance"},
    {"slug": "attendance:update", "name": "Update attendance"},
    # Reports (3)
    {"slug": "reports:read", "name": "View reports"},
    {"slug": "reports:generate", "name": "Generate reports"},
    {"slug": "reports:override", "name": "Override council decisions"},
    # Parents (4)
    {"slug": "admin:parents:read", "name": "View parents"},
    {"slug": "admin:parents:create", "name": "Create parents"},
    {"slug": "admin:parents:update", "name": "Update parents"},
    {"slug": "admin:parents:delete", "name": "Delete parents"},
    # Roles & Permissions management (2)
    {"slug": "admin:roles:read", "name": "View roles and permissions"},
    {"slug": "admin:roles:write", "name": "Manage roles and permissions"},
    # Rooms (4)
    {"slug": "admin:rooms:read", "name": "View rooms"},
    {"slug": "admin:rooms:create", "name": "Create rooms"},
    {"slug": "admin:rooms:update", "name": "Update rooms"},
    {"slug": "admin:rooms:delete", "name": "Delete rooms"},
    # Series (2)
    {"slug": "admin:series:read", "name": "View academic series"},
    {"slug": "admin:series:write", "name": "Manage academic series"},
    # Super Admin (1)
    {"slug": "super-admin:tenants:create", "name": "Provision new tenants"},
]

# ---------------------------------------------------------------------------
# Role definitions with their permission slugs
# ---------------------------------------------------------------------------

ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "admin": {
        "description": "Administrateur — accès complet",
        "permissions": [p["slug"] for p in ALL_PERMISSIONS],
    },
    "director": {
        "description": "Directeur d'établissement",
        "permissions": [p["slug"] for p in ALL_PERMISSIONS],
    },
    "teacher": {
        "description": "Enseignant",
        "permissions": [
            "grades:read",
            "grades:write",
            "bulletins:generate",
            "attendance:read",
            "attendance:create",
            "attendance:update",
            "timetable:read",
            "reports:read",
        ],
    },
    "staff": {
        "description": "Personnel administratif",
        "permissions": [
            "enrollments:read",
            "enrollments:create",
            "enrollments:update",
            "payments:read",
            "payments:create",
            "admin:students:read",
            "admin:students:create",
            "admin:students:update",
            "admin:classes:read",
            "attendance:read",
            "reports:read",
        ],
    },
    "accountant": {
        "description": "Comptable / Trésorier",
        "permissions": [
            "payments:read",
            "payments:create",
            "enrollments:read",
            "reports:read",
        ],
    },
    "student": {
        "description": "Élève — accès portail élève uniquement",
        "permissions": [],
    },
    "parent": {
        "description": "Parent / Tuteur — accès portail parent uniquement",
        "permissions": [],
    },
}
# Note: student and parent roles have NO permissions (portal is user-scoped via JWT)


async def create_tenant_database(tenant_slug: str) -> None:
    """Step 1: Create the MySQL database for the tenant."""
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
    """Step 2: Run all Alembic migrations on the tenant database."""
    env = os.environ.copy()
    env["TENANT_ID"] = tenant_slug

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic migration failed for tenant '{tenant_slug}': {result.stderr}")
    logger.info("Migrations applied for tenant '%s'", tenant_slug)


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
    """Step 3: Seed permissions, roles, admin user, and school settings."""
    tenant_url = settings.DATABASE_URL.format(tenant=tenant_slug)
    engine = create_async_engine(tenant_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with factory() as db:
            async with db.begin():
                # 3a. Seed permissions
                for perm in ALL_PERMISSIONS:
                    await db.execute(
                        text("INSERT IGNORE INTO permissions (slug, name) VALUES (:slug, :name)"),
                        perm,
                    )

                # 3b. Seed roles and link permissions
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

                # 3c. Create admin user
                hashed = hash_password(admin_password)
                await db.execute(
                    text(
                        "INSERT INTO users (email, hashed_password, role, is_active) "
                        "VALUES (:email, :hashed, 'admin', 1)"
                    ),
                    {"email": admin_email, "hashed": hashed},
                )
                admin_result = await db.execute(
                    text("SELECT id FROM users WHERE email = :email"),
                    {"email": admin_email},
                )
                admin_user_id = admin_result.scalar_one()

                # 3d. Assign admin role to admin user
                admin_role_result = await db.execute(
                    text("SELECT id FROM roles WHERE name = 'admin'"),
                )
                admin_role_id = admin_role_result.scalar_one()
                await db.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"),
                    {"user_id": admin_user_id, "role_id": admin_role_id},
                )

                # 3e. Create StaffProfile for admin
                await db.execute(
                    text(
                        "INSERT INTO staff_profiles (user_id, first_name, last_name, position) "
                        "VALUES (:user_id, 'Admin', :school_name, 'Administrateur')"
                    ),
                    {"user_id": admin_user_id, "school_name": school_name},
                )

                # 3f. Seed school settings
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
    """Full provisioning workflow: create DB -> migrate -> seed -> welcome email."""
    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$", tenant_slug):
        raise ValueError(
            f"Invalid tenant_slug '{tenant_slug}': "
            "must be 2-63 chars, lowercase alphanumeric + hyphens"
        )

    logger.info("=== Provisioning tenant '%s' ===", tenant_slug)

    # Step 1: Create database
    await create_tenant_database(tenant_slug)

    # Step 2: Run migrations
    await run_migrations(tenant_slug)

    # Step 3: Seed data
    result = await seed_tenant_data(
        tenant_slug,
        school_name=school_name,
        admin_email=admin_email,
        admin_password=admin_password,
        school_address=school_address,
        school_phone=school_phone,
        school_email=school_email,
        ministry_code=ministry_code,
    )

    # Step 4: Welcome email (best-effort — n'interrompt pas si SMTP fail)
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
        "admin_email": result["admin_email"],
        "tenant_url": f"https://{tenant_slug}.college.klassci.com",
        "welcome_email_sent": email_sent,
        "status": "provisioned",
    }
