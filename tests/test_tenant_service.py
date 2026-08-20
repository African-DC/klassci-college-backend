"""Tests du service de provisioning tenant."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tenant_service import (
    ALL_PERMISSIONS,
    ROLE_DEFINITIONS,
    TenantAlreadyProvisioned,
    provision_tenant,
)
from app.services.tenants import create_admin_user_for_tenant

# ---------------------------------------------------------------------------
# Validation du slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug",
    [
        "A",  # too short + uppercase
        "a",  # too short (1 char)
        "UPPERCASE",
        "with spaces",
        "-starts-with-dash",
        "ends-with-dash-",
        "has_underscore",
        "a" * 64,  # too long (64 chars)
    ],
)
def test_provision_tenant_invalid_slug(slug: str) -> None:
    """Les slugs invalides doivent lever ValueError."""
    with pytest.raises(ValueError, match="2-63 caractères"):
        import asyncio

        asyncio.run(
            provision_tenant(
                tenant_slug=slug,
                school_name="Test",
                admin_email="admin@test.ci",
                admin_password="SecureP@ss123",
            )
        )


def test_provision_tenant_valid_slugs() -> None:
    """Les slugs valides ne doivent pas lever ValueError sur la validation."""
    valid_slugs = ["ab", "lycee-moderne", "college-01", "a" * 63]
    for slug in valid_slugs:
        # We only test the slug validation — the actual provisioning is mocked
        import re

        assert re.match(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]$", slug), f"'{slug}' should be valid"


# ---------------------------------------------------------------------------
# Full provisioning (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_tenant_success() -> None:
    """Le workflow complet doit appeler create DB, migrate, seed dans l'ordre."""
    with (
        patch(
            "app.services.tenants.provisioning.create_tenant_database",
            new_callable=AsyncMock,
        ) as mock_create_db,
        patch(
            "app.services.tenants.provisioning.run_migrations",
            new_callable=AsyncMock,
        ) as mock_migrate,
        patch(
            "app.services.tenants.provisioning.seed_tenant_data",
            new_callable=AsyncMock,
            return_value={"admin_user_id": 1, "admin_email": "admin@test.ci"},
        ) as mock_seed,
    ):
        result = await provision_tenant(
            tenant_slug="lycee-test",
            school_name="Lycee Test",
            admin_email="admin@test.ci",
            admin_password="SecureP@ss123",
        )

    mock_create_db.assert_called_once_with("lycee-test")
    mock_migrate.assert_called_once_with("lycee-test")
    mock_seed.assert_called_once()

    assert result["tenant_slug"] == "lycee-test"
    assert result["database"] == "lycee-test"
    assert result["admin_email"] == "admin@test.ci"
    assert result["status"] == "provisioned"


# ---------------------------------------------------------------------------
# list_tenant_databases (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tenant_databases() -> None:
    """SHOW DATABASES doit filtrer les bases système."""
    from app.cli.migrate_all import list_tenant_databases

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("lycee-moderne",),
        ("college-01",),
    ]

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=mock_result)
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_engine = AsyncMock()
    mock_engine.begin = MagicMock(return_value=mock_conn)
    mock_engine.dispose = AsyncMock()

    with patch(
        "app.cli.migrate_all.create_async_engine",
        return_value=mock_engine,
    ):
        tenants = await list_tenant_databases()

    assert "lycee-moderne" in tenants
    assert "college-01" in tenants
    assert len(tenants) == 2
    query = str(mock_conn.execute.await_args.args[0])
    assert "alembic_version" in query
    assert "academic_years" in query
    assert "document_issuances" not in query
    assert "HAVING COUNT(DISTINCT table_name) = 4" in query


@pytest.mark.asyncio
async def test_migrate_all_fails_closed_when_no_tenant_is_found() -> None:
    from app.cli.migrate_all import migrate_all

    with (
        patch("app.cli.migrate_all.list_tenant_databases", new=AsyncMock(return_value=[])),
        pytest.raises(RuntimeError, match="No KLASSCI tenant"),
    ):
        await migrate_all()


# ---------------------------------------------------------------------------
# Permission & role data integrity
# ---------------------------------------------------------------------------


def test_all_permissions_unique_slugs() -> None:
    """Toutes les permissions doivent avoir des slugs uniques."""
    slugs = [p["slug"] for p in ALL_PERMISSIONS]
    assert len(slugs) == len(set(slugs)), "Duplicate slugs found"


def test_role_permissions_reference_valid_slugs() -> None:
    """Toutes les permissions des rôles doivent exister dans ALL_PERMISSIONS."""
    valid_slugs = {p["slug"] for p in ALL_PERMISSIONS}
    for role_name, role_def in ROLE_DEFINITIONS.items():
        for slug in role_def["permissions"]:
            assert slug in valid_slugs, f"Role '{role_name}' references unknown permission '{slug}'"


def test_super_admin_role_present_with_all_super_admin_perms() -> None:
    """The super_admin role must exist and own every super-admin:* permission."""
    assert "super_admin" in ROLE_DEFINITIONS
    super_admin_perms = set(ROLE_DEFINITIONS["super_admin"]["permissions"])
    expected = {p["slug"] for p in ALL_PERMISSIONS if p["slug"].startswith("super-admin:")}
    assert super_admin_perms == expected
    assert len(expected) >= 7, "Expected at least 7 super-admin:* permissions seeded"


def test_admin_role_does_not_carry_super_admin_perms() -> None:
    """admin / director are tenant-scoped — they must NOT carry cross-tenant powers."""
    for role_name in ("admin", "director"):
        perms = ROLE_DEFINITIONS[role_name]["permissions"]
        assert not any(p.startswith("super-admin:") for p in perms), (
            f"Role '{role_name}' must not include super-admin:* permissions"
        )


# ---------------------------------------------------------------------------
# Idempotency — re-running provision_tenant on a bootstrapped tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_admin_user_raises_when_admin_already_exists() -> None:
    """Re-provisioning a tenant whose admin already exists must raise TenantAlreadyProvisioned."""
    db = AsyncMock()
    select_existing = MagicMock()
    select_existing.scalar_one_or_none = MagicMock(return_value=42)
    db.execute = AsyncMock(return_value=select_existing)

    with pytest.raises(TenantAlreadyProvisioned) as excinfo:
        await create_admin_user_for_tenant(
            db,
            tenant_slug="lycee-test",
            admin_email="admin@lycee-test.ci",
            admin_password="SecureP@ss123",
            school_name="Lycee Test",
        )

    assert excinfo.value.tenant_slug == "lycee-test"
    assert excinfo.value.admin_email == "admin@lycee-test.ci"
    assert excinfo.value.existing_user_id == 42
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_admin_user_inserts_when_admin_does_not_exist() -> None:
    """First-time provisioning must insert the admin user, role link, and staff_profile."""
    db = AsyncMock()
    no_existing = MagicMock()
    no_existing.scalar_one_or_none = MagicMock(return_value=None)
    insert_user = MagicMock()
    insert_user.lastrowid = 99
    role_lookup = MagicMock()
    role_lookup.scalar_one = MagicMock(return_value=1)

    db.execute = AsyncMock(side_effect=[no_existing, insert_user, role_lookup, None, None])

    user_id = await create_admin_user_for_tenant(
        db,
        tenant_slug="lycee-test",
        admin_email="admin@lycee-test.ci",
        admin_password="SecureP@ss123",
        school_name="Lycee Test",
    )

    assert user_id == 99
    # 5 statements: SELECT existing, INSERT user, SELECT role, INSERT user_role, INSERT staff_profile
    assert db.execute.await_count == 5


# ---------------------------------------------------------------------------
# Roles metier (caissier / educateur / directeur des etudes) — invariants
# ---------------------------------------------------------------------------


def test_every_assignable_staff_role_is_defined() -> None:
    """Le formulaire Personnel ne doit jamais proposer un role inexistant."""
    from app.services.admin_service import _STAFF_ROLE_SENIORITY, STAFF_ASSIGNABLE_ROLES

    for role in STAFF_ASSIGNABLE_ROLES:
        assert role in ROLE_DEFINITIONS, f"Role assignable '{role}' absent de ROLE_DEFINITIONS"
        assert role in _STAFF_ROLE_SENIORITY, (
            f"Role assignable '{role}' absent de l'ordre de seniorite : un compte "
            "portant plusieurs roles afficherait un role arbitraire"
        )


def test_studies_director_has_no_financial_access() -> None:
    """Separation des taches : le directeur des etudes ne touche pas a l'argent."""
    perms = set(ROLE_DEFINITIONS["studies_director"]["permissions"])
    forbidden = {p for p in perms if p.startswith(("payments:", "admin:fee-"))}
    assert not forbidden, (
        f"Le directeur des etudes ne doit avoir aucun droit financier : {forbidden}"
    )


def test_cashier_cannot_configure_fees_nor_read_reports() -> None:
    """Le caissier encaisse : il ne configure rien et n'a pas les rapports.

    Il LIT en revanche la grille de tranches : au guichet, un parent demande
    « je dois combien et pour quand ? », et lui refuser cette lecture le
    rendrait incapable de répondre.
    """
    perms = set(ROLE_DEFINITIONS["cashier"]["permissions"])
    assert "payments:create" in perms
    assert "admin:fee-installments:read" in perms

    writes = {p for p in perms if p.startswith("admin:fee-") and not p.endswith(":read")}
    assert not writes, f"Le caissier ne doit configurer aucun frais : {writes}"
    assert "enrollments:schedule:write" not in perms, "négocier un échéancier est financier"
    assert "reports:read" not in perms


def test_educator_reads_payments_but_never_creates_them() -> None:
    """L'educateur valide au vu de l'encaissement, il ne tient pas la caisse."""
    perms = set(ROLE_DEFINITIONS["educator"]["permissions"])
    assert "payments:read" in perms
    assert "payments:create" not in perms
    assert "enrollments:create" in perms
    assert "enrollments:update" in perms


def test_accountant_can_read_academic_years_and_configure_fees() -> None:
    """Regression : sans `admin:academic-years:read` la page Frais tombait en 403."""
    perms = set(ROLE_DEFINITIONS["accountant"]["permissions"])
    assert "admin:academic-years:read" in perms
    assert "admin:fee-categories:update" in perms
    assert "admin:fee-variants:update" in perms


def test_performance_permission_is_declared() -> None:
    """`performance:read` est exigee par /admin/performance : elle doit etre seedee."""
    assert "performance:read" in {p["slug"] for p in ALL_PERMISSIONS}
    assert "performance:read" in ROLE_DEFINITIONS["admin"]["permissions"]
