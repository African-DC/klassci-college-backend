"""Cross-tenant read queries for super-admin endpoints.

These functions deliberately bypass the JWT-scoped `get_tenant_db()` because
listing tenants and computing per-tenant stats requires connections to other
tenant DBs. Each call opens its own short-lived engine and disposes it.

Heavy ops (e.g. row counts on big tables) are kept O(1) at the SQL level
(COUNT(*) on indexed PK columns) so listing 50 tenants stays under ~500 ms.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

_SYSTEM_DATABASES = {
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
    "alembic_migration",
}


def _management_url() -> str:
    return settings.DATABASE_URL.replace("/{tenant}", "/")


def _tenant_url(slug: str) -> str:
    return settings.DATABASE_URL.format(tenant=slug)


async def list_tenant_slugs() -> list[str]:
    """Return all tenant DB names from information_schema, sorted."""
    engine = create_async_engine(_management_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "ORDER BY schema_name ASC"
                )
            )
            rows = result.fetchall()
    finally:
        await engine.dispose()
    return [row[0] for row in rows if row[0] not in _SYSTEM_DATABASES]


async def slug_exists(slug: str) -> bool:
    engine = create_async_engine(_management_url(), isolation_level="AUTOCOMMIT")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.schemata " "WHERE schema_name = :slug LIMIT 1"
                ),
                {"slug": slug},
            )
            return result.scalar_one_or_none() is not None
    finally:
        await engine.dispose()


async def get_tenant_summary(slug: str) -> dict[str, Any] | None:
    """Return a small dict summarising the tenant or None if the DB doesn't exist."""
    if not await slug_exists(slug):
        return None

    engine = create_async_engine(_tenant_url(slug), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            settings_row = await conn.execute(
                text(
                    "SELECT school_name, address, phone, email, ministry_code "
                    "FROM school_settings ORDER BY id LIMIT 1"
                )
            )
            school_settings = settings_row.fetchone()

            counts = {}
            for table, key in (
                ("users", "users"),
                ("students", "students"),
                ("teacher_profiles", "teachers"),
                ("staff_profiles", "staff"),
                ("enrollments", "enrollments"),
                ("payments", "payments"),
            ):
                row = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[key] = int(row.scalar_one())

            alembic_row = await conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            alembic_head = alembic_row.scalar_one_or_none()

            db_size_row = await conn.execute(
                text(
                    "SELECT COALESCE(SUM(data_length + index_length), 0) "
                    "FROM information_schema.tables WHERE table_schema = :slug"
                ),
                {"slug": slug},
            )
            db_size_bytes = int(db_size_row.scalar_one() or 0)
    finally:
        await engine.dispose()

    return {
        "slug": slug,
        "url": f"https://{slug}.college.klassci.com",
        "school_settings": _settings_dict(school_settings),
        "counts": counts,
        "alembic_head": alembic_head,
        "db_size_bytes": db_size_bytes,
    }


def _settings_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "school_name": row[0],
        "address": row[1],
        "phone": row[2],
        "email": row[3],
        "ministry_code": row[4],
    }


async def get_tenants_overview() -> list[dict[str, Any]]:
    """Return a lightweight list view: slug + school_name + db_size + user count."""
    slugs = await list_tenant_slugs()
    items: list[dict[str, Any]] = []

    if not slugs:
        return items

    engine = create_async_engine(_management_url(), isolation_level="AUTOCOMMIT")
    try:
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
    finally:
        await engine.dispose()

    for slug in slugs:
        items.append(
            {
                "slug": slug,
                "url": f"https://{slug}.college.klassci.com",
                "db_size_bytes": sizes.get(slug, 0),
                "created_at": _approx_created_from_alembic(slug),
            }
        )
    return items


def _approx_created_from_alembic(_slug: str) -> datetime | None:
    """Placeholder — exact creation date requires a master tenants table.

    Returning None for now; can be filled later by introspecting the earliest
    alembic_version row or by adding a `created_at` column to school_settings.
    """
    return None
