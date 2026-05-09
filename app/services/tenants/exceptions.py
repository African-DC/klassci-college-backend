"""Tenant-specific exceptions."""


class TenantAlreadyProvisioned(Exception):
    """Raised when re-running provision_tenant for an already-bootstrapped tenant.

    The presence of an admin User row with the requested email is treated as
    the canonical signal that the tenant is fully bootstrapped (DB + migrations
    + seed have all completed at least once).

    Re-running is refused rather than silently re-applying because the original
    admin password is unknown to the operator and overwriting it could lock
    out a real user.
    """

    def __init__(self, tenant_slug: str, admin_email: str, existing_user_id: int):
        self.tenant_slug = tenant_slug
        self.admin_email = admin_email
        self.existing_user_id = existing_user_id
        super().__init__(
            f"Tenant '{tenant_slug}' is already provisioned "
            f"(admin '{admin_email}' exists with id={existing_user_id}). "
            f"Drop the database first if you really want to re-provision."
        )
