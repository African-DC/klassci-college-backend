"""Tests for /super-admin/logs and /super-admin/db/query (risky Path F endpoints)."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.dependencies import TokenData, get_current_user, get_tenant_db
from app.core.redis import get_redis
from app.main import app
from app.services.logs_service import LogReadResult

JWT_USER = TokenData(user_id=1, tenant_id="local", email="superadmin@klassci.com")


def _override() -> None:
    app.dependency_overrides[get_current_user] = lambda: JWT_USER
    app.dependency_overrides[get_tenant_db] = lambda: AsyncMock()
    app.dependency_overrides[get_redis] = lambda: AsyncMock()


def _clear() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /super-admin/logs
# ---------------------------------------------------------------------------


def test_logs_returns_redacted_lines() -> None:
    _override()
    result = LogReadResult(
        lines=["2026-05-09 10:00 starting", "2026-05-09 10:01 user=[REDACTED-EMAIL]"],
        truncated=False,
        redacted_count=1,
    )
    try:
        with patch(
            "app.routers.super_admin.logs.read_service_logs",
            return_value=result,
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/logs?service=klassci-backend&lines=10")
    finally:
        _clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "klassci-backend"
    assert len(body["lines"]) == 2
    assert body["redacted_count"] == 1


def test_logs_invalid_service_name_400() -> None:
    _override()
    try:
        with TestClient(app) as client:
            resp = client.get("/super-admin/logs?service=bad;rm -rf&lines=5")
    finally:
        _clear()
    assert resp.status_code == 400


def test_logs_reader_unavailable_returns_501() -> None:
    _override()
    try:
        with patch(
            "app.routers.super_admin.logs.read_service_logs",
            side_effect=NotImplementedError("logs not available"),
        ):
            with TestClient(app) as client:
                resp = client.get("/super-admin/logs?service=klassci-backend&lines=5")
    finally:
        _clear()
    assert resp.status_code == 501


def test_windows_log_reader_reads_nssm_files(tmp_path, monkeypatch) -> None:
    from app.services.logs_service import read_windows_service_logs

    monkeypatch.setenv("KLASSCI_LOG_DIR", str(tmp_path))
    (tmp_path / "backend.err.log").write_text(
        "user admin@klassci.com tried to login\nAuthorization: Bearer secret-token\n",
        encoding="utf-8",
    )

    result = read_windows_service_logs("klassci-backend", 10)

    assert len(result.lines) == 2
    assert "[REDACTED-EMAIL]" in result.lines[0]
    assert "[REDACTED]" in result.lines[1]
    assert result.redacted_count >= 2


def test_logs_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.get("/super-admin/logs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Redaction unit checks
# ---------------------------------------------------------------------------


def test_redact_strips_authorization_header() -> None:
    from app.services.logs_service import redact

    line = "GET /api/users Authorization: Bearer eyJhbGc.eyJzdWIiOjF9.signature123 200 OK"
    out, n = redact(line)
    assert "Bearer" not in out or "[REDACTED]" in out
    assert n >= 1


def test_redact_strips_pat_pattern() -> None:
    from app.services.logs_service import redact

    line = "auth using klc_pat_abcdef0123456789abcdef0123456789"
    out, n = redact(line)
    assert "klc_pat_" not in out
    assert "[REDACTED-PAT]" in out
    assert n == 1


def test_redact_strips_emails() -> None:
    from app.services.logs_service import redact

    line = "user admin@klassci.com tried to login"
    out, n = redact(line)
    assert "admin@klassci.com" not in out
    assert "[REDACTED-EMAIL]" in out


# ---------------------------------------------------------------------------
# /super-admin/db/query
# ---------------------------------------------------------------------------


def test_db_query_dry_run_returns_warnings_without_executing() -> None:
    _override()
    try:
        with patch("app.routers.super_admin.db_query.execute_sql") as mock_exec:
            with TestClient(app) as client:
                resp = client.post(
                    "/super-admin/db/query",
                    json={
                        "tenant_slug": "local",
                        "sql": "DROP TABLE students",
                        "dry_run": True,
                    },
                )
    finally:
        _clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    codes = [w["code"] for w in body["warnings"]]
    assert "DROP_STATEMENT" in codes
    assert mock_exec.call_count == 0


def test_db_query_rejects_multi_statement() -> None:
    _override()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/super-admin/db/query",
                json={
                    "tenant_slug": "local",
                    "sql": "SELECT 1; DROP TABLE x",
                    "dry_run": True,
                },
            )
    finally:
        _clear()
    assert resp.status_code == 422


def test_db_query_executes_when_dry_run_false() -> None:
    _override()
    outcome = {
        "rowcount": 2,
        "columns": ["id", "email"],
        "rows": [[1, "a@b.ci"], [2, "c@d.ci"]],
        "elapsed_ms": 12.3,
        "truncated": False,
    }
    try:
        with patch(
            "app.routers.super_admin.db_query.execute_sql",
            new_callable=AsyncMock,
            return_value=outcome,
        ):
            with TestClient(app) as client:
                resp = client.post(
                    "/super-admin/db/query",
                    json={
                        "tenant_slug": "local",
                        "sql": "SELECT id, email FROM users LIMIT 2",
                        "dry_run": False,
                    },
                )
    finally:
        _clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is False
    assert body["rowcount"] == 2
    assert body["columns"] == ["id", "email"]
    assert len(body["rows"]) == 2


def test_db_query_warnings_include_delete_without_where() -> None:
    from app.services.db_query_service import analyse_sql

    warnings = analyse_sql("DELETE FROM students")
    codes = [w["code"] for w in warnings]
    assert "DELETE_WITHOUT_WHERE" in codes


def test_db_query_warnings_skip_safe_select() -> None:
    from app.services.db_query_service import analyse_sql

    assert analyse_sql("SELECT * FROM students WHERE id = 1") == []


def test_db_query_unauthenticated() -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/super-admin/db/query",
            json={"tenant_slug": "local", "sql": "SELECT 1", "dry_run": True},
        )
    assert resp.status_code == 401


def test_db_query_invalid_slug_422() -> None:
    _override()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/super-admin/db/query",
                json={"tenant_slug": "BAD SLUG", "sql": "SELECT 1", "dry_run": True},
            )
    finally:
        _clear()
    assert resp.status_code == 422
