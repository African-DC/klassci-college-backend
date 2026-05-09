"""End-to-end CLI tests via Click's CliRunner."""

import json
from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from app.cli.klassci import cli


def _runner_args(*extra: str) -> list[str]:
    """Common CLI args: env-set token (skips keyring entirely)."""
    return list(extra)


def test_help_does_not_require_token() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "klassci" in result.output.lower()


def test_subcommand_help_does_not_require_token() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["tenant", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output
    assert "show" in result.output


def test_tenant_list_renders_human_table(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    payload = {
        "items": [
            {
                "slug": "lycee-moderne",
                "url": "https://lycee-moderne.college.klassci.com",
                "db_size_bytes": 12345678,
            },
        ],
        "total": 1,
    }
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.get", new_callable=AsyncMock, return_value=payload
    ):
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            result = runner.invoke(cli, ["tenant", "list"])
    assert result.exit_code == 0, result.output
    assert "lycee-moderne" in result.output
    assert "1 tenant(s)" in result.output


def test_tenant_list_json_format(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    payload = {"items": [{"slug": "x", "url": "u", "db_size_bytes": 0}], "total": 1}
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.get", new_callable=AsyncMock, return_value=payload
    ):
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            result = runner.invoke(cli, ["--format", "json", "tenant", "list"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output.strip())
    assert parsed[0]["slug"] == "x"


def test_tenant_check_slug_available(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    payload = {"slug": "new", "available": True, "valid_format": True, "reason": None}
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.post", new_callable=AsyncMock, return_value=payload
    ):
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            result = runner.invoke(cli, ["tenant", "check-slug", "new"])
    assert result.exit_code == 0, result.output
    assert "available" in result.output


def test_pat_revoke_requires_confirmation_by_default(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.delete", new_callable=AsyncMock, return_value=204
    ) as mock_del:
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            # answer "no" to the confirmation prompt
            result = runner.invoke(cli, ["pat", "revoke", "42"], input="n\n")
    assert "Annulé" in result.output
    assert mock_del.call_count == 0


def test_pat_revoke_with_yes_flag(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.delete", new_callable=AsyncMock, return_value=204
    ) as mock_del:
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            result = runner.invoke(cli, ["pat", "revoke", "42", "--yes"])
    assert result.exit_code == 0, result.output
    mock_del.assert_awaited_once_with("/super-admin/pats/42")


def test_doctor_renders_overall_status(monkeypatch) -> None:
    monkeypatch.setenv("KLASSCI_TOKEN", "klc_pat_dummy")
    payload = {
        "overall": "degraded",
        "checks": [
            {"component": "backend", "status": "ok", "message": None},
            {"component": "smtp", "status": "degraded", "message": "SMTP_HOST not set"},
        ],
        "timestamp": "2026-05-09T12:00:00",
    }
    runner = CliRunner()
    with patch(
        "app.cli.dispatcher.RemoteDispatcher.get", new_callable=AsyncMock, return_value=payload
    ):
        with patch("app.cli.dispatcher.RemoteDispatcher.aclose", new_callable=AsyncMock):
            result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "DEGRADED" in result.output


def test_login_rejects_non_pat_format() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--token", "not-a-pat"])
    assert result.exit_code != 0
    assert "Format invalide" in result.output


def test_login_with_valid_token(tmp_path, monkeypatch) -> None:
    """Successful login saves the token and prints the user's email."""
    runner = CliRunner()
    response_mock = type(
        "R",
        (),
        {"status_code": 200, "json": lambda self: {"email": "marcel@klassci.com"}},
    )()
    with (
        patch("app.cli.commands.login.httpx.get", return_value=response_mock),
        patch("app.cli.commands.login.save_token") as mock_save,
    ):
        result = runner.invoke(
            cli,
            ["login", "--token", "klc_pat_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "--profile", "ci"],
        )
    assert result.exit_code == 0, result.output
    assert "marcel@klassci.com" in result.output
    mock_save.assert_called_once()


def test_remote_mode_without_token_fails(monkeypatch) -> None:
    """Running an authenticated command without any stored token fails clearly."""
    monkeypatch.delenv("KLASSCI_TOKEN", raising=False)
    runner = CliRunner()
    with patch("app.cli.auth.get_token", return_value=None):
        result = runner.invoke(cli, ["tenant", "list"])
    assert result.exit_code != 0
    assert "Pas de token" in result.output or "klassci login" in result.output
