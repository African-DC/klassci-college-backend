"""Bordereau de Ma caisse : toujours la caisse de l'appelant.

Le consolidé du comptable reste sur `GET /payments/daily-cash-book`. Cet
endpoint ne doit jamais s'ouvrir, même si l'appelant a `payments:read:all`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

CAISSIERE = TokenData(user_id=12, tenant_id="local", email="sophie.yao@college.ci")
ADMIN_GUICHET = TokenData(user_id=1, tenant_id="local", email="admin@college.ci")
COMPTABLE = TokenData(user_id=3, tenant_id="local", email="comptable@college.ci")


def _mock_infra() -> AsyncMock:
    return AsyncMock()


def _client(qui: TokenData, *, permissions: set[str]) -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: qui
    app.dependency_overrides[get_tenant_db] = _mock_infra
    app.dependency_overrides[get_redis] = _mock_infra

    async def _check(_db: object, _user_id: int, slug: str) -> bool:
        return slug in permissions

    try:
        with patch(
            "app.repositories.permission_repository.check_user_permission",
            new=_check,
        ):
            yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def caissiere() -> Iterator[TestClient]:
    yield from _client(CAISSIERE, permissions={"cash-session:manage", "payments:read"})


@pytest.fixture
def admin_guichet() -> Iterator[TestClient]:
    yield from _client(
        ADMIN_GUICHET,
        permissions={
            "cash-session:manage",
            "cash-session:read:all",
            "payments:read",
            "payments:read:all",
        },
    )


@pytest.fixture
def comptable() -> Iterator[TestClient]:
    yield from _client(
        COMPTABLE,
        permissions={"cash-session:read:all", "payments:read", "payments:read:all"},
    )


def _kwargs(export: AsyncMock) -> dict[str, object]:
    return export.call_args.kwargs


def test_la_caissiere_imprime_sa_caisse(caissiere: TestClient) -> None:
    with patch(
        "app.routers.cash_sessions.daily_cash_book_service.get_daily_cash_book_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = caissiere.get("/cash-sessions/me/daily-cash-book?date=2026-08-30")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("application/pdf")
    assert _kwargs(export)["restrict_to_cashier"] is True
    assert _kwargs(export)["cashier_user_id"] == CAISSIERE.user_id
    assert export.call_args.args[1] == date(2026, 8, 30)


def test_un_admin_au_guichet_n_imprime_pas_le_consolide(admin_guichet: TestClient) -> None:
    with patch(
        "app.routers.cash_sessions.daily_cash_book_service.get_daily_cash_book_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = admin_guichet.get("/cash-sessions/me/daily-cash-book?date=2026-08-30")

    assert reponse.status_code == 200
    assert _kwargs(export)["restrict_to_cashier"] is True
    assert _kwargs(export)["cashier_user_id"] == ADMIN_GUICHET.user_id


def test_un_parametre_etranger_ne_change_pas_la_caisse(caissiere: TestClient) -> None:
    with patch(
        "app.routers.cash_sessions.daily_cash_book_service.get_daily_cash_book_pdf",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.7 test",
    ) as export:
        reponse = caissiere.get(
            "/cash-sessions/me/daily-cash-book?date=2026-08-30&cashier_id=99"
        )

    assert reponse.status_code == 200
    assert _kwargs(export)["cashier_user_id"] == CAISSIERE.user_id
    assert _kwargs(export)["restrict_to_cashier"] is True


def test_le_comptable_sans_guichet_est_refuse(comptable: TestClient) -> None:
    reponse = comptable.get("/cash-sessions/me/daily-cash-book?date=2026-08-30")
    assert reponse.status_code == 403
