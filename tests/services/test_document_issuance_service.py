from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import settings
from app.core.database import current_tenant_id
from app.core.exceptions import BusinessValidationError
from app.models.document_issuance import DocumentIssuance
from app.services import document_issuance_service as service


def make_pending_issuance() -> DocumentIssuance:
    return DocumentIssuance(
        id=42,
        token="public-token",
        cev_code="SNI-AAAA-BBBB-CCCC-DDDD",
        seal_code="SNI-AAAA-BBBB-CCCC-DDDD",
        document_type="certificat_scolarite",
        reference="CS-2026-001",
        student_name="Aminata Traoré",
        class_name="3e A",
        academic_year="2025-2026",
        student_id=7,
        issued_at=datetime(2026, 7, 21, 12, 0, 0),
        scheme_version=service.SCHEME_CURRENT,
        signature_algorithm=service.SIGNATURE_ALGORITHM,
        key_id=settings.DOCUMENT_SEAL_ACTIVE_KEY_ID,
        source_sha256="c" * 64,
        status=service.STATUS_PENDING,
        revision=1,
        expires_at=datetime(2027, 7, 21, 12, 0, 0),
    )


@pytest.mark.asyncio
async def test_repeated_certificate_download_reuses_archived_pdf() -> None:
    issuance = make_pending_issuance()
    issuance.status = service.STATUS_ACTIVE
    issuance.pdf_content = b"%PDF-1.7 archived"
    result = MagicMock()
    result.scalars.return_value.all.return_value = [issuance]
    db = AsyncMock()
    db.execute.return_value = result

    verification = await service.issue_document(
        db,
        document_type=issuance.document_type,
        reference=issuance.reference,
        student_name=issuance.student_name,
        class_name=issuance.class_name,
        academic_year=issuance.academic_year,
        student_id=issuance.student_id,
        issued_at=issuance.issued_at + timedelta(days=1),
        source_sha256=issuance.source_sha256 or "",
    )

    assert verification.issuance_id == issuance.id
    assert verification.sealed_pdf == b"%PDF-1.7 archived"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_active_archive_is_reused_even_when_a_later_pending_exists() -> None:
    active = make_pending_issuance()
    active.status = service.STATUS_ACTIVE
    active.pdf_content = b"%PDF-1.7 archived"
    pending = make_pending_issuance()
    pending.id = 43
    pending.revision = 2
    result = MagicMock()
    result.scalars.return_value.all.return_value = [pending, active]
    db = AsyncMock()
    db.execute.return_value = result

    verification = await service.issue_document(
        db,
        document_type=active.document_type,
        reference=active.reference,
        student_name=active.student_name,
        class_name=active.class_name,
        academic_year=active.academic_year,
        student_id=active.student_id,
        issued_at=active.issued_at,
        source_sha256=active.source_sha256 or "",
    )

    assert verification.issuance_id == active.id
    assert verification.sealed_pdf == active.pdf_content
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_expired_archive_creates_a_new_revision() -> None:
    expired = make_pending_issuance()
    expired.status = service.STATUS_ACTIVE
    expired.pdf_content = b"%PDF-1.7 expired"
    expired.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [expired]
    db = AsyncMock()
    db.execute.return_value = result
    db.add = MagicMock()

    verification = await service.issue_document(
        db,
        document_type=expired.document_type,
        reference=expired.reference,
        student_name=expired.student_name,
        class_name=expired.class_name,
        academic_year=expired.academic_year,
        student_id=expired.student_id,
        issued_at=expired.issued_at,
        source_sha256=expired.source_sha256 or "",
    )

    assert verification.sealed_pdf is None
    db.add.assert_called_once()
    created = db.add.call_args.args[0]
    assert created.revision == 2
    assert created.supersedes_id == expired.id


@pytest.mark.asyncio
async def test_stale_pending_is_failed_before_retry() -> None:
    pending = make_pending_issuance()
    pending.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [pending]
    db = AsyncMock()
    db.execute.return_value = result
    db.add = MagicMock()

    await service.issue_document(
        db,
        document_type=pending.document_type,
        reference=pending.reference,
        student_name=pending.student_name,
        class_name=pending.class_name,
        academic_year=pending.academic_year,
        student_id=pending.student_id,
        issued_at=pending.issued_at,
        source_sha256=pending.source_sha256 or "",
    )

    assert pending.status == service.STATUS_FAILED
    assert pending.failed_at is not None
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_recent_pending_blocks_a_different_revision() -> None:
    pending = make_pending_issuance()
    pending.created_at = datetime.now(UTC).replace(tzinfo=None)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [pending]
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(BusinessValidationError, match="déjà en cours"):
        await service.issue_document(
            db,
            document_type=pending.document_type,
            reference=pending.reference,
            student_name=pending.student_name,
            class_name="Une autre classe",
            academic_year=pending.academic_year,
            student_id=pending.student_id,
            issued_at=pending.issued_at,
            source_sha256="d" * 64,
        )

    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_finalize_signs_exact_pdf_and_public_key_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")
    issuance = make_pending_issuance()
    db = AsyncMock()
    db.get.return_value = issuance
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    tenant_token = current_tenant_id.set("local")
    try:
        finalized = await service.finalize_document(db, issuance.id, b"%PDF-1.7 original")
    finally:
        current_tenant_id.reset(tenant_token)

    assert finalized.status == service.STATUS_ACTIVE
    assert len(finalized.document_sha256 or "") == 64
    assert finalized.signature
    assert service.verify_signature(finalized, tenant="local") is True
    assert service.verify_pdf_bytes(finalized, b"%PDF-1.7 original", tenant="local") is True
    assert service.verify_pdf_bytes(finalized, b"%PDF-1.7 modified", tenant="local") is False


@pytest.mark.asyncio
async def test_older_pending_revision_cannot_finalize_after_a_newer_one() -> None:
    older = make_pending_issuance()
    newer = make_pending_issuance()
    newer.id = 43
    newer.revision = 2
    result = MagicMock()
    result.scalar_one_or_none.return_value = newer
    db = AsyncMock()
    db.get.return_value = older
    db.execute.return_value = result

    with pytest.raises(BusinessValidationError, match="révision plus récente"):
        await service.finalize_document(db, older.id, b"%PDF-1.7 older")

    assert older.status == service.STATUS_SUPERSEDED
    assert older.superseded_by_id == newer.id
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_rejects_rebinding_existing_seal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")
    issuance = make_pending_issuance()
    db = AsyncMock()
    db.get.return_value = issuance
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    await service.finalize_document(db, issuance.id, b"%PDF-1.7 original")

    with pytest.raises(ValueError, match="different PDF bytes"):
        await service.finalize_document(db, issuance.id, b"%PDF-1.7 modified")


def test_signature_tampering_and_unknown_key_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")
    issuance = make_pending_issuance()
    issuance.status = service.STATUS_ACTIVE
    issuance.document_sha256 = "a" * 64
    issuance.signature = "invalid-signature"
    assert service.verify_signature(issuance, tenant="local") is False

    issuance.signature = service._b64encode(b"0" * 64)
    issuance.key_id = "retired-key-not-in-keyring"
    assert service.verify_signature(issuance, tenant="local") is False


def test_retired_public_key_can_verify_historical_seal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")
    old_private = Ed25519PrivateKey.from_private_bytes(b"R" * 32)
    old_public = old_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setattr(
        settings,
        "DOCUMENT_SEAL_PUBLIC_KEYS_JSON",
        f'{{"retired-2025":"{service._b64encode(old_public)}"}}',
    )
    issuance = make_pending_issuance()
    issuance.status = service.STATUS_ACTIVE
    issuance.document_sha256 = "b" * 64
    issuance.key_id = "retired-2025"
    issuance.signature = service._b64encode(
        old_private.sign(service._current_payload(issuance, "local"))
    )

    assert service.verify_signature(issuance, tenant="local") is True


def test_legacy_document_remains_verifiable() -> None:
    issuance = make_pending_issuance()
    issuance.scheme_version = service.SCHEME_LEGACY
    issuance.seal_code = None
    issuance.signature_algorithm = None
    issuance.key_id = None
    issuance.document_sha256 = None
    issuance.signature = None
    issuance.status = service.STATUS_ACTIVE
    issuance.cev_code = service._legacy_code(
        service._legacy_signing_key().sign(service._legacy_payload(issuance, "local"))
    )

    assert service.verify_signature(issuance, tenant="local") is True


def test_expiration_is_derived_from_signed_deadline() -> None:
    issuance = make_pending_issuance()
    issuance.status = service.STATUS_ACTIVE
    issuance.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)

    assert service.effective_status(issuance) == service.STATUS_EXPIRED


def test_legacy_key_fails_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "DOCUMENT_SEAL_LEGACY_SECRET_KEY", "")

    with pytest.raises(RuntimeError, match="LEGACY_SECRET_KEY"):
        service._legacy_signing_key()


@pytest.mark.asyncio
async def test_mark_document_failed_closes_pending_issuance() -> None:
    issuance = make_pending_issuance()
    db = AsyncMock()
    db.get.return_value = issuance

    await service.mark_document_failed(db, issuance.id, reason="Renderer failed")

    assert issuance.status == service.STATUS_FAILED
    assert issuance.failed_at is not None
    assert issuance.failure_reason == "Renderer failed"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revocation_is_irreversible() -> None:
    issuance = make_pending_issuance()
    issuance.status = service.STATUS_ACTIVE
    db = AsyncMock()
    db.get.return_value = issuance

    revoked = await service.revoke_document(
        db, issuance.id, reason="Document remplacé", revoked_by=99
    )
    assert revoked.status == service.STATUS_REVOKED
    assert revoked.revoked_by_id == 99
    assert revoked.revocation_reason == "Document remplacé"

    with pytest.raises(ValueError, match="Cannot revoke"):
        await service.revoke_document(db, issuance.id, reason="Deuxième révocation", revoked_by=99)
