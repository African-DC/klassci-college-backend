"""Seed deterministic test users for E2E pipelines and local development.

Idempotent — safe to re-run. Reads `DATABASE_URL` from env (with `{tenant}`
placeholder substituted to the value of the `TENANT_ID` env var, defaulting
to `local`). All users get the same password to keep the E2E suite simple.

Users seeded:
- admin@klassci.com  → role admin, with StaffProfile
- prof@klassci.com   → role teacher, with TeacherProfile
- eleve@klassci.com  → role student, with Student profile (enrollment_number=E2E001)

Run locally:
    TENANT_ID=local python scripts/seed_test_users.py

Run in CI (after alembic upgrade head):
    DATABASE_URL=mysql+aiomysql://root:root@127.0.0.1:3306/{tenant} \\
    TENANT_ID=klassci_test \\
    python scripts/seed_test_users.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Allow running as `python scripts/seed_test_users.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PASSWORD = "Admin@2026"

USERS: list[dict[str, Any]] = [
    {
        "email": "admin@klassci.com",
        "role": "admin",
        "profile": {"table": "staff_profiles", "first_name": "Admin", "last_name": "KLASSCI"},
    },
    {
        "email": "prof@klassci.com",
        "role": "teacher",
        "profile": {
            "table": "teacher_profiles",
            "first_name": "Aïssatou",
            "last_name": "Diallo",
        },
    },
    {
        "email": "eleve@klassci.com",
        "role": "student",
        "profile": {
            "table": "students",
            "first_name": "Aminata",
            "last_name": "Traoré",
            "enrollment_number": "E2E001",
        },
    },
]


def _resolve_database_url() -> str:
    """Substitute `{tenant}` in DATABASE_URL with TENANT_ID env or 'local'."""
    tenant = os.environ.get("TENANT_ID", "local")
    raw = settings.DATABASE_URL
    return raw.format(tenant=tenant) if "{tenant}" in raw else raw


async def _ensure_user(db: Any, email: str, role: str, profile: dict[str, Any]) -> None:
    """Insert user + role link + profile (idempotent — skip if email exists)."""
    existing = await db.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    )
    user_id = existing.scalar_one_or_none()

    if user_id is None:
        await db.execute(
            text(
                "INSERT INTO users (email, hashed_password, role, is_active) "
                "VALUES (:email, :hashed, :role, 1)"
            ),
            {"email": email, "hashed": hash_password(PASSWORD), "role": role},
        )
        result = await db.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email},
        )
        user_id = result.scalar_one()
        logger.info("Created user %s (id=%s)", email, user_id)
    else:
        logger.info("User %s already exists (id=%s) — skipping insert", email, user_id)

    # Link to role row in user_roles (idempotent — INSERT IGNORE on UNIQUE).
    await db.execute(
        text(
            "INSERT IGNORE INTO user_roles (user_id, role_id) "
            "SELECT :user_id, id FROM roles WHERE name = :role_name"
        ),
        {"user_id": user_id, "role_name": role},
    )

    # Create the persona-specific profile if missing.
    table = profile["table"]
    if table == "staff_profiles":
        await db.execute(
            text(
                "INSERT IGNORE INTO staff_profiles (user_id, first_name, last_name, position) "
                "VALUES (:user_id, :first_name, :last_name, 'Administrateur')"
            ),
            {
                "user_id": user_id,
                "first_name": profile["first_name"],
                "last_name": profile["last_name"],
            },
        )
    elif table == "teacher_profiles":
        await db.execute(
            text(
                "INSERT IGNORE INTO teacher_profiles "
                "(user_id, first_name, last_name, speciality) "
                "VALUES (:user_id, :first_name, :last_name, 'Mathématiques')"
            ),
            {
                "user_id": user_id,
                "first_name": profile["first_name"],
                "last_name": profile["last_name"],
            },
        )
    elif table == "students":
        await db.execute(
            text(
                "INSERT IGNORE INTO students "
                "(user_id, first_name, last_name, enrollment_number) "
                "VALUES (:user_id, :first_name, :last_name, :enrollment_number)"
            ),
            {
                "user_id": user_id,
                "first_name": profile["first_name"],
                "last_name": profile["last_name"],
                "enrollment_number": profile["enrollment_number"],
            },
        )


async def main() -> None:
    url = _resolve_database_url()
    logger.info("Seeding test users on %s", url.replace(url.split("@")[0], "***"))

    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as db, db.begin():
            for spec in USERS:
                await _ensure_user(
                    db,
                    email=spec["email"],
                    role=spec["role"],
                    profile=spec["profile"],
                )
        logger.info("Seed complete (%d users guaranteed).", len(USERS))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
