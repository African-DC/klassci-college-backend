"""Contrat HTTP idempotent vers MailPulse pour KLASSCI College."""

from unittest.mock import AsyncMock

import pytest

from app.services.mailpulse.client import (
    MailPulseClient,
    MailPulseResult,
    message_idempotency_key,
)


@pytest.mark.asyncio
async def test_send_email_uses_required_mailpulse_idempotency_header(monkeypatch):
    client = MailPulseClient(api_key="test-only", base_url="https://mailpulse.example")
    post = AsyncMock(return_value=MailPulseResult(ok=True, status="queued"))
    monkeypatch.setattr(client, "_post", post)

    await client.send_message(
        channel="email",
        recipient="direction@ecole.ci",
        subject="Activation",
        body="Bienvenue",
        external_event_id="activation:tenant-42",
    )

    kwargs = post.await_args.kwargs
    key = kwargs["idempotency_key"]
    assert key.startswith("college:event:")
    assert "direction@ecole.ci" not in key
    assert client._headers(key)["idempotency-key"] == key


def test_business_event_retries_have_stable_and_recipient_scoped_keys():
    base = {"channel": "email", "recipient": "a@ecole.ci", "external_event_id": "paiement:42"}
    first = message_idempotency_key(explicit_key=None, **base)
    assert message_idempotency_key(explicit_key=None, **base) == first
    assert message_idempotency_key(explicit_key=None, **{**base, "recipient": "b@ecole.ci"}) != first
    assert message_idempotency_key(explicit_key=None, **{**base, "external_event_id": "paiement:43"}) != first


def test_manual_messages_get_fresh_keys_and_explicit_keys_win():
    opts = {"channel": "whatsapp", "recipient": "+2250102030405", "external_event_id": None}
    first = message_idempotency_key(explicit_key=None, **opts)
    second = message_idempotency_key(explicit_key=None, **opts)
    assert first != second
    assert message_idempotency_key(explicit_key="retry-key-123", **opts) == "retry-key-123"
