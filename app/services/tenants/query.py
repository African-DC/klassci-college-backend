"""Cross-tenant read queries for super-admin endpoints.

These functions deliberately bypass the JWT-scoped `get_tenant_db()` because
listing tenants and computing per-tenant stats requires connections to other
tenant DBs. Each call opens a short-lived engine via `short_lived_engine`.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.database import (
    SYSTEM_DATABASES,
    management_database_url,
    tenant_database_url,
)
from app.services.tenants._engine import short_lived_engine


async def list_tenant_slugs() -> list[str]:
    """Return all tenant DB names from information_schema, sorted."""
    async with short_lived_engine(
        management_database_url(), isolation_level="AUTOCOMMIT"
    ) as engine:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name ASC")
            )
            rows = result.fetchall()
    return [row[0] for row in rows if row[0] not in SYSTEM_DATABASES]


async def slug_exists(slug: str) -> bool:
    async with short_lived_engine(
        management_database_url(), isolation_level="AUTOCOMMIT"
    ) as engine:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :slug LIMIT 1"),
                {"slug": slug},
            )
            return result.scalar_one_or_none() is not None


async def get_tenant_summary(slug: str) -> dict[str, Any] | None:
    """Return a small dict summarising the tenant or None if the DB doesn't exist.

    Skips the pre-existence check: opens the per-tenant engine directly and
    treats unknown-database errors (MySQL 1049) as "not found".
    """
    try:
        async with short_lived_engine(tenant_database_url(slug), pool_pre_ping=True) as engine:
            async with engine.begin() as conn:
                settings_result = await conn.execute(
                    text(
                        "SELECT school_name, address, phone, email, ministry_code "
                        "FROM school_settings ORDER BY id LIMIT 1"
                    )
                )
                school_settings = settings_result.mappings().first()

                counts_row = await conn.execute(
                    text(
                        "SELECT "
                        "  (SELECT COUNT(*) FROM users)            AS users, "
                        "  (SELECT COUNT(*) FROM students)         AS students, "
                        "  (SELECT COUNT(*) FROM teacher_profiles) AS teachers, "
                        "  (SELECT COUNT(*) FROM staff_profiles)   AS staff, "
                        "  (SELECT COUNT(*) FROM enrollments)      AS enrollments, "
                        "  (SELECT COUNT(*) FROM payments)         AS payments"
                    )
                )
                counts = dict(counts_row.mappings().one())

                alembic_row = await conn.execute(
                    text("SELECT version_num FROM alembic_version LIMIT 1")
                )
                alembic_head = alembic_row.scalar_one_or_none()

                size_row = await conn.execute(
                    text(
                        "SELECT COALESCE(SUM(data_length + index_length), 0) "
                        "FROM information_schema.tables WHERE table_schema = :slug"
                    ),
                    {"slug": slug},
                )
                db_size_bytes = int(size_row.scalar_one() or 0)
    except (OperationalError, ProgrammingError) as exc:
        if _is_unknown_database(exc):
            return None
        raise

    return {
        "slug": slug,
        "url": f"https://{slug}.college.klassci.com",
        "school_settings": dict(school_settings) if school_settings else None,
        "counts": {k: int(v) for k, v in counts.items()},
        "alembic_head": alembic_head,
        "db_size_bytes": db_size_bytes,
    }


def _is_unknown_database(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "1049" in msg or "unknown database" in msg


async def get_tenants_overview() -> list[dict[str, Any]]:
    """Lightweight list view: slug + url + db_size."""
    slugs = await list_tenant_slugs()
    if not slugs:
        return []

    async with short_lived_engine(
        management_database_url(), isolation_level="AUTOCOMMIT"
    ) as engine:
        async with engine.begin() as conn:
            placeholders = ", ".join(f":s{i}" for i in range(len(slugs)))
            params = {f"s{i}": slug for i, slug in enumerate(slugs)}
            sizes_result = await conn.execute(
                text(
                    "SELECT table_schema, COALESCE(SUM(data_length + index_length), 0) "
                    "FROM information_schema.tables "
                    f"WHERE table_schema IN ({placeholders}) "
                    "GROUP BY table_schema"
                ),
                params,
            )
            sizes = {row[0]: int(row[1]) for row in sizes_result.fetchall()}

    return [
        {
            "slug": slug,
            "url": f"https://{slug}.college.klassci.com",
            "db_size_bytes": sizes.get(slug, 0),
        }
        for slug in slugs
    ]
