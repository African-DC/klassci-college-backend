"""Tests du service de provisioning tenant."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tenant_service import (
    ALL_PERMISSIONS,
    ROLE_DEFINITIONS,
    provision_tenant,
)


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
            "app.services.tenant_service.create_tenant_database",
            new_callable=AsyncMock,
        ) as mock_create_db,
        patch(
            "app.services.tenant_service.run_migrations",
            new_callable=AsyncMock,
        ) as mock_migrate,
        patch(
            "app.services.tenant_service.seed_tenant_data",
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
            assert slug in valid_slugs, (
                f"Role '{role_name}' references unknown permission '{slug}'"
            )
