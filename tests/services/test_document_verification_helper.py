from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services._document_verification_helper import render_verification


@pytest.mark.asyncio
async def test_cancelled_render_closes_pending_seal() -> None:
    db = AsyncMock()
    verification = {
        "issuance_id": 42,
        "reference": "CS-2026-001",
        "seal_code": "SNI-AAAA-BBBB-CCCC-DDDD",
        "verify_url": "https://example.test/verifier/local/token",
        "manual_verify_url": "https://example.test/verifier?tenant=local",
        "cev_svg": "<svg />",
        "sealed_pdf": None,
    }

    def cancel_render() -> bytes:
        raise asyncio.CancelledError

    failed = AsyncMock()
    with (
        patch("app.services.document_issuance_service.mark_document_failed", new=failed),
        pytest.raises(asyncio.CancelledError),
    ):
        await render_verification(db, verification, cancel_render)

    failed.assert_awaited_once()
