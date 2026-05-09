"""Tests du service de provisioning tenant."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tenant_service import (
    ALL_PERMISSIONS,
    ROLE_DEFINITIONS,
    TenantAlreadyProvisioned,
    provision_tenant,
)
from app.services.tenants.provisioning import _create_admin_user

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
    with pytest.raises(ValueError, match="Invalid tenant_slug"):
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
        ("information_schema",),
        ("mysql",),
        ("performance_schema",),
        ("sys",),
        ("alembic_migration",),
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
    assert "mysql" not in tenants
    assert "information_schema" not in tenants
    assert "sys" not in tenants
    assert len(tenants) == 2


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
        assert not any(
            p.startswith("super-admin:") for p in perms
        ), f"Role '{role_name}' must not include super-admin:* permissions"


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
        await _create_admin_user(
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
    inserted_lookup = MagicMock()
    inserted_lookup.scalar_one = MagicMock(return_value=99)
    role_lookup = MagicMock()
    role_lookup.scalar_one = MagicMock(return_value=1)

    db.execute = AsyncMock(
        side_effect=[no_existing, None, inserted_lookup, role_lookup, None, None]
    )

    user_id = await _create_admin_user(
        db,
        tenant_slug="lycee-test",
        admin_email="admin@lycee-test.ci",
        admin_password="SecureP@ss123",
        school_name="Lycee Test",
    )

    assert user_id == 99
    assert db.execute.await_count == 6
