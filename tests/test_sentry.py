"""Tests for app.core.sentry — no-op behaviour + sensitive header redaction."""

from unittest.mock import patch

from app.core.sentry import _strip_sensitive_data, init_sentry


def test_init_sentry_noop_when_dsn_empty() -> None:
    """init_sentry must not import sentry_sdk nor raise when DSN is empty."""
    with patch("app.core.sentry.settings.SENTRY_DSN", ""):
        # Should not raise. The early return prevents any Sentry SDK import.
        init_sentry()


def test_strip_sensitive_data_redacts_auth_headers() -> None:
    """before_send hook redacts Authorization / Cookie / X-API-Key headers."""
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token-xyz",
                "Cookie": "session=abc; refresh=xyz",
                "X-API-Key": "key-123",
                "User-Agent": "pytest",
                "Content-Type": "application/json",
            },
            "cookies": {"session": "abc"},
        },
    }

    result = _strip_sensitive_data(event, {})

    headers = result["request"]["headers"]
    assert headers["Authorization"] == "[redacted]"
    assert headers["Cookie"] == "[redacted]"
    assert headers["X-API-Key"] == "[redacted]"
    # Non-sensitive headers preserved
    assert headers["User-Agent"] == "pytest"
    assert headers["Content-Type"] == "application/json"
    # Cookies dict should be removed entirely
    assert "cookies" not in result["request"]


def test_strip_sensitive_data_handles_no_request() -> None:
    """before_send is robust when the event has no request dict."""
    event: dict[str, object] = {"level": "error", "message": "boom"}

    result = _strip_sensitive_data(event, {})

    assert result == event


def test_strip_sensitive_data_handles_non_dict_headers() -> None:
    """before_send tolerates list-of-pairs headers (some integrations emit those)."""
    event = {"request": {"headers": [("Authorization", "Bearer x")]}}

    # Should not raise — just leaves the list untouched
    result = _strip_sensitive_data(event, {})

    assert result == event
