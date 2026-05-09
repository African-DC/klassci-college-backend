"""Raw-SQL execution against any tenant DB. Risky by design (Path F).

Mitigations:
- ``dry_run=True`` mode returns warnings without executing — agents and
  humans should always preview first.
- Heuristic warnings flag DROP / TRUNCATE / DELETE-without-WHERE.
- Multi-statement queries are rejected at the schema layer.
- Result rows truncated to ``limit`` to bound memory.
- Every execution is audit-logged via the dispatching router.
"""

import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import tenant_database_url
from app.services.tenants._engine import short_lived_engine

_DANGER_PATTERNS = [
    (re.compile(r"\bDROP[ \t]+(TABLE|DATABASE|INDEX|VIEW)\b", re.IGNORECASE), "DROP_STATEMENT"),
    (re.compile(r"\bTRUNCATE\b", re.IGNORECASE), "TRUNCATE_STATEMENT"),
    (re.compile(r"\bALTER[ \t]+TABLE\b", re.IGNORECASE), "ALTER_TABLE"),
    (re.compile(r"\bGRANT\b", re.IGNORECASE), "GRANT_STATEMENT"),
    (re.compile(r"\bREVOKE\b", re.IGNORECASE), "REVOKE_STATEMENT"),
]
# Use bounded fixed-width whitespace classes (no `\s+\s*` overlap) to avoid
# polynomial backtracking on adversarial SQL inputs.
_WHERE_LESS_DELETE = re.compile(r"\bDELETE[ \t]+FROM[ \t]+\w+[ \t]*(?:;|$)", re.IGNORECASE)
_WHERE_LESS_UPDATE = re.compile(r"\bUPDATE[ \t]+\w+[ \t]+SET[ \t]+[^;]+?(?:;|$)", re.IGNORECASE)


def analyse_sql(sql: str) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for pattern, code in _DANGER_PATTERNS:
        if pattern.search(sql):
            warnings.append({"code": code, "message": f"{code} detected", "severity": "danger"})
    if _WHERE_LESS_DELETE.search(sql):
        warnings.append(
            {
                "code": "DELETE_WITHOUT_WHERE",
                "message": "DELETE statement without a WHERE clause — full table wipe",
                "severity": "danger",
            }
        )
    if _WHERE_LESS_UPDATE.search(sql) and "WHERE" not in sql.upper():
        warnings.append(
            {
                "code": "UPDATE_WITHOUT_WHERE",
                "message": "UPDATE statement without a WHERE clause — every row affected",
                "severity": "danger",
            }
        )
    return warnings


async def execute_sql(
    tenant_slug: str,
    sql: str,
    *,
    limit: int,
) -> dict[str, Any]:
    from app.core.slug import validate_tenant_slug

    validate_tenant_slug(tenant_slug)
    start = time.perf_counter()
    async with short_lived_engine(tenant_database_url(tenant_slug), pool_pre_ping=True) as engine:
        async with engine.begin() as conn:
            try:
                result = await conn.execute(text(sql))
            except SQLAlchemyError as exc:
                raise RuntimeError(f"SQL error: {exc.__class__.__name__}: {exc}") from exc

            elapsed_ms = (time.perf_counter() - start) * 1000

            if result.returns_rows:
                fetched = result.fetchmany(limit + 1)
                truncated = len(fetched) > limit
                rows = fetched[:limit]
                columns = list(result.keys())
                serialised = [[_serialise(v) for v in row] for row in rows]
                return {
                    "rowcount": len(rows),
                    "columns": columns,
                    "rows": serialised,
                    "elapsed_ms": elapsed_ms,
                    "truncated": truncated,
                }

            return {
                "rowcount": result.rowcount,
                "columns": [],
                "rows": [],
                "elapsed_ms": elapsed_ms,
                "truncated": False,
            }


def _serialise(value: Any) -> Any:
    """Convert non-JSON-friendly values (datetime, Decimal, bytes) to strings."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)
