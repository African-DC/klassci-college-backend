"""Backwards-compatible facade — routes imports through `app.services.tenants`.

The body of this module was split into focused submodules per the
no-god-code rule. New code should import directly from `app.services.tenants`;
this facade exists only so external callers (cli/provision_tenant.py,
existing tests, future operations layer) stay unbroken.
"""

from app.services.tenants import (
    ALL_PERMISSIONS,
    ROLE_DEFINITIONS,
    TenantAlreadyProvisioned,
    create_tenant_database,
    provision_tenant,
    run_migrations,
    seed_tenant_data,
)

__all__ = [
    "ALL_PERMISSIONS",
    "ROLE_DEFINITIONS",
    "TenantAlreadyProvisioned",
    "create_tenant_database",
    "provision_tenant",
    "run_migrations",
    "seed_tenant_data",
]
