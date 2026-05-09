"""Super-admin router package — one file per sub-domain (no-god-code rule)."""

from fastapi import APIRouter

from app.routers.super_admin import db_query, diagnose, logs, pats, tenants

router = APIRouter(prefix="/super-admin")
router.include_router(tenants.router)
router.include_router(pats.router)
router.include_router(diagnose.router)
router.include_router(logs.router)
router.include_router(db_query.router)
