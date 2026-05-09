"""Tenant slug regex + validation — single source of truth.

The pattern matches RFC 1123 subdomain format: 2-63 chars, lowercase
alphanumeric + hyphens, no leading/trailing hyphen. Used by middleware
host validation, JWT claim acceptance, schema validators, and routers.

Drift between the four call sites silently breaks tenants — keep them
all importing from here.
"""

import re

TENANT_SLUG_PATTERN = r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$"
TENANT_SLUG_RE: re.Pattern[str] = re.compile(TENANT_SLUG_PATTERN)


def is_valid_tenant_slug(value: str) -> bool:
    return bool(TENANT_SLUG_RE.match(value))


def validate_tenant_slug(value: str) -> str:
    """Return the slug if valid, else raise ValueError with a stable message."""
    if not is_valid_tenant_slug(value):
        raise ValueError(
            "Doit faire 2-63 caractères, minuscules + chiffres + tirets, "
            "sans tiret en début ni en fin."
        )
    return value
