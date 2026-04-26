"""Shared pytest fixtures for the KLASSCI College backend test suite.

Backwards-compatible: existing tests that define their own
``_override_deps`` / ``MOCK_USER`` helpers continue to work. New tests
can opt into the fixtures below to remove boilerplate.

Usage::

    def test_admin_lists_students(client):
        response = client.get("/admin/students")
        assert response.status_code in {200, 401}

    def test_anon_can_hit_health(anon_client):
        response = anon_client.get("/health")
        assert response.status_code == 200
"""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.core.database import current_tenant_id
from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app

# ---------------------------------------------------------------------------
# Tenant context — scoped to the test by default
# ---------------------------------------------------------------------------


@pytest.fixture
def tenant_local() -> Generator[str, None, None]:
    """Set the tenant ContextVar to ``local`` for the duration of one test.

    Opt-in: tests that need a different tenant set it explicitly.
    """
    token = current_tenant_id.set("local")
    try:
        yield "local"
    finally:
        current_tenant_id.reset(token)


# ---------------------------------------------------------------------------
# Time + identity primitives
# ---------------------------------------------------------------------------


@pytest.fixture
def now() -> datetime:
    """Single ``datetime.now(UTC)`` shared by a test for stable comparisons."""
    return datetime.now(UTC)


@pytest.fixture
def admin_token() -> TokenData:
    """Authenticated admin user on the ``local`` tenant."""
    return TokenData(user_id=1, tenant_id="local", email="admin@college.ci")


@pytest.fixture
def teacher_token() -> TokenData:
    """Authenticated teacher user on the ``local`` tenant."""
    return TokenData(user_id=2, tenant_id="local", email="prof@college.ci")


@pytest.fixture
def student_token() -> TokenData:
    """Authenticated student user on the ``local`` tenant."""
    return TokenData(user_id=3, tenant_id="local", email="eleve@college.ci")


# ---------------------------------------------------------------------------
# Mock infra — DB + Redis
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> AsyncMock:
    """``AsyncMock`` standing in for an async SQLAlchemy session.

    Intended use: tests that mock the *service* layer above the DB. Tests
    that exercise DB code should use a real session in a transaction.
    """
    return AsyncMock()


@pytest.fixture
def mock_redis() -> AsyncMock:
    """``AsyncMock`` standing in for an aioredis client."""
    return AsyncMock()


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------


@pytest.fixture
def client(
    admin_token: TokenData,
    mock_db: AsyncMock,
    mock_redis: AsyncMock,
) -> Generator[TestClient, None, None]:
    """``TestClient`` with admin auth + mocked DB/Redis dependencies.

    Override individual deps inside the test via ``app.dependency_overrides``
    if you need a different role/db. Cleanup is automatic.
    """
    app.dependency_overrides[get_current_user] = lambda: admin_token
    app.dependency_overrides[get_tenant_db] = lambda: mock_db
    app.dependency_overrides[get_redis] = lambda: mock_redis
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def anon_client() -> Generator[TestClient, None, None]:
    """``TestClient`` without dependency overrides — for public routes."""
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client_as():
    """Factory: spawn a TestClient with a specific TokenData identity.

    Example::

        def test_teacher_route(client_as, teacher_token, mock_db):
            with client_as(teacher_token, db=mock_db) as c:
                response = c.get("/teacher/dashboard")
    """
    from contextlib import contextmanager

    @contextmanager
    def _factory(
        token: TokenData,
        *,
        db: AsyncMock | None = None,
        redis: AsyncMock | None = None,
    ) -> Generator[TestClient, None, None]:
        app.dependency_overrides[get_current_user] = lambda: token
        app.dependency_overrides[get_tenant_db] = lambda: db or AsyncMock()
        app.dependency_overrides[get_redis] = lambda: redis or AsyncMock()
        try:
            yield TestClient(app)
        finally:
            app.dependency_overrides.clear()

    return _factory
