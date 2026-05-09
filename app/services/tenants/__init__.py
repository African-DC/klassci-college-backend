"""Tenant operations package — split per concern (no-god-code rule).

Public API kept intentionally small. New tenant ops should land in a
focused submodule (lifecycle.py, query.py) rather than this __init__.
"""

from app.services.tenants.exceptions import TenantAlreadyProvisioned
from app.services.tenants.permissions import ALL_PERMISSIONS, ROLE_DEFINITIONS
from app.services.tenants.provisioning import (
    create_tenant_database,
    provision_tenant,
    run_migrations,
    seed_tenant_data,
)
from app.services.tenants.query import (
    get_tenant_summary,
    get_tenants_overview,
    list_tenant_slugs,
    slug_exists,
)

__all__ = [
    "ALL_PERMISSIONS",
    "ROLE_DEFINITIONS",
    "TenantAlreadyProvisioned",
    "create_tenant_database",
    "get_tenant_summary",
    "get_tenants_overview",
    "list_tenant_slugs",
    "provision_tenant",
    "run_migrations",
    "seed_tenant_data",
    "slug_exists",
]
