"""Tenant slug regex + validation — single source of truth.

The pattern matches RFC 1123 subdomain format: 2-63 chars, lowercase
alphanumeric + hyphens, no leading/trailing hyphen. Used by middleware
host validation, JWT claim acceptance, schema validators, and routers.

Two validation tiers:
- ``validate_tenant_slug`` (regex only): defensive boundary checks on
  slugs that may already exist (provisioning re-runs, middleware
  resolution). Tolerant of the historical ``local`` system tenant.
- ``validate_new_tenant_slug`` (regex + reserved): API-side validation
  at the moment a new tenant is being created. Rejects reserved names
  that would collide with system paths or future infrastructure.

Drift between the four call sites silently breaks tenants — keep them
all importing from here.
"""

import re

# `\A` et `\Z` plutôt que `^` et `$`.
#
# En Python, `$` accepte une fin de chaîne **ou** la position juste avant un
# saut de ligne final : un slug terminé par un saut de ligne passait donc la
# validation. Le slug finit
# entre accents graves dans un `CREATE DATABASE`, qui ne peut pas prendre de
# paramètre lié — la classe de caractères y interdit l'accent grave et le
# point-virgule, donc aucune injection n'était possible, mais une base pouvait
# naître avec un saut de ligne dans son nom, indiscernable à l'affichage de
# celle qui n'en a pas.
TENANT_SLUG_PATTERN = r"\A[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]\Z"
TENANT_SLUG_RE: re.Pattern[str] = re.compile(TENANT_SLUG_PATTERN)

# Slugs that must never be assigned to a new tenant: they collide with
# platform paths, common SaaS conventions, or the system tenant itself.
# Kept frozenset for O(1) membership and immutable contract.
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        # System tenant
        "local",
        # Platform path conflicts (URL routes)
        "admin",
        "super-admin",
        "api",
        "auth",
        "login",
        "logout",
        "signup",
        # SaaS conventions
        "www",
        "app",
        "mail",
        "static",
        "cdn",
        "docs",
        "blog",
        "status",
        "health",
        "metrics",
        "support",
        # Environment names (avoid confusion)
        "test",
        "dev",
        "staging",
        "prod",
        "production",
    }
)


def is_valid_tenant_slug(value: str) -> bool:
    return bool(TENANT_SLUG_RE.match(value))


def is_reserved_tenant_slug(value: str) -> bool:
    return value in RESERVED_SLUGS


def validate_tenant_slug(value: str) -> str:
    """Return the slug if format-valid, else raise ValueError.

    Format check only. Does NOT reject reserved names — use
    ``validate_new_tenant_slug`` for that. This function is the
    defensive boundary used internally on slugs that may already
    exist (e.g. re-seeding the system tenant ``local``).
    """
    if not is_valid_tenant_slug(value):
        raise ValueError(
            "Doit faire 2-63 caractères, minuscules + chiffres + tirets, "
            "sans tiret en début ni en fin."
        )
    return value


def validate_new_tenant_slug(value: str) -> str:
    """Return the slug if it can be assigned to a new tenant, else raise.

    Stricter than ``validate_tenant_slug``: rejects format-invalid AND
    reserved names. Use at the API boundary (provisioning request,
    slug availability check) — never on resolution paths.
    """
    validate_tenant_slug(value)
    if is_reserved_tenant_slug(value):
        raise ValueError(
            f"Le slug '{value}' est réservé (système ou collision avec un "
            "chemin plateforme). Choisir un autre identifiant."
        )
    return value
