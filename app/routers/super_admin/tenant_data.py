"""Read-only cross-tenant entity browsing under /super-admin/tenants/{slug}/...

Returns lightweight row dicts. Full per-entity admin endpoints (CRUD,
filters, search) belong on /admin/* with proper tenant context — these
are the super-admin equivalents for cross-tenant ad-hoc browsing.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.core.dependencies import require_permission
from app.core.slug import is_valid_tenant_slug
from app.services.tenants.cross_tenant import (
    count_rows,
    list_classes,
    list_students,
    list_teachers,
)

router = APIRouter(prefix="/tenants/{slug}", tags=["super-admin"])


def _check_slug(slug: str) -> None:
    if not is_valid_tenant_slug(slug):
        raise HTTPException(status_code=400, detail="Invalid slug format")


async def _safe_run(slug: str, table: str, lister) -> dict[str, Any]:
    _check_slug(slug)
    try:
        items = await lister
        total = await count_rows(slug, table)
    except (OperationalError, ProgrammingError) as exc:
        msg = str(exc).lower()
        if "1049" in msg or "unknown database" in msg:
            raise HTTPException(status_code=404, detail=f"Tenant '{slug}' not found") from exc
        raise
    return {"items": items, "total": total}


@router.get("/students", summary="List students of a tenant (read-only)")
async def get_students(
    slug: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = require_permission("super-admin:tenants:read"),
) -> dict[str, Any]:
    payload = await _safe_run(slug, "students", list_students(slug, limit=limit, offset=offset))
    return {**payload, "limit": limit, "offset": offset}


@router.get("/teachers", summary="List teachers of a tenant (read-only)")
async def get_teachers(
    slug: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = require_permission("super-admin:tenants:read"),
) -> dict[str, Any]:
    payload = await _safe_run(slug, "teachers", list_teachers(slug, limit=limit, offset=offset))
    return {**payload, "limit": limit, "offset": offset}


@router.get("/classes", summary="List classes of a tenant (read-only)")
async def get_classes(
    slug: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: None = require_permission("super-admin:tenants:read"),
) -> dict[str, Any]:
    payload = await _safe_run(slug, "classes", list_classes(slug, limit=limit, offset=offset))
    return {**payload, "limit": limit, "offset": offset}
