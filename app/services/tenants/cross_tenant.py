"""Cross-tenant SELECT helpers for super-admin entity browsing.

Each function opens a short-lived engine bound to the target tenant DB
and returns plain dicts. No SQLAlchemy ORM session, no model imports —
this is a deliberately minimal read-only surface.

Use the ``operate_on`` argument to pass paginated parameters (limit /
offset) without building yet another query DSL.
"""

from typing import Any

from sqlalchemy import text

from app.core.database import tenant_database_url
from app.services.tenants._engine import short_lived_engine


async def _select_dicts(
    tenant_slug: str, sql: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    async with short_lived_engine(tenant_database_url(tenant_slug), pool_pre_ping=True) as engine:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            rows = result.mappings().all()
    return [dict(r) for r in rows]


async def list_students(tenant_slug: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    return await _select_dicts(
        tenant_slug,
        """
        SELECT id, first_name, last_name, enrollment_number, genre, birth_date,
               birth_place, photo_url, city, commune, created_at
        FROM students
        ORDER BY last_name, first_name
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )


async def list_teachers(tenant_slug: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    return await _select_dicts(
        tenant_slug,
        """
        SELECT t.id, t.first_name, t.last_name, t.speciality, t.phone,
               u.email, u.is_active
        FROM teacher_profiles t
        JOIN users u ON u.id = t.user_id
        ORDER BY t.last_name, t.first_name
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )


async def list_classes(tenant_slug: str, *, limit: int, offset: int) -> list[dict[str, Any]]:
    return await _select_dicts(
        tenant_slug,
        """
        SELECT id, name, code, level_id, series_id, max_capacity, created_at
        FROM classes
        ORDER BY name
        LIMIT :limit OFFSET :offset
        """,
        {"limit": limit, "offset": offset},
    )


_ALLOWED_COUNT_TABLES = frozenset(
    {"students", "teacher_profiles", "teachers", "staff_profiles", "classes", "users"}
)


async def count_rows(tenant_slug: str, table: str) -> int:
    """Count rows for a single allow-listed table on the target tenant.

    Strict allowlist (not just regex) because the table name reaches a raw
    f-string SQL — a typo upstream that lets through e.g. ``students; --``
    must be impossible by construction.
    """
    if table not in _ALLOWED_COUNT_TABLES:
        raise ValueError(f"Table '{table}' not in count allowlist")
    async with short_lived_engine(tenant_database_url(tenant_slug), pool_pre_ping=True) as engine:
        async with engine.begin() as conn:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            return int(result.scalar_one())
