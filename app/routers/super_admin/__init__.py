"""Super-admin router package — one file per sub-domain (no-god-code rule).

Currently mounted:
- tenants  → provision / list / show / check-slug

Future sub-routers (Sprint 1.2+):
- pats        → personal access token CRUD
- diagnose    → platform + per-tenant health
- logs        → journalctl proxy with redaction
- db_query    → raw SQL with confirmation token
"""

from fastapi import APIRouter

from app.routers.super_admin import tenants

router = APIRouter(prefix="/super-admin")
router.include_router(tenants.router)
