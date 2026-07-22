"""Institutional document seal issuance and verification.

New documents use the KSI2 scheme. A random manual code and Datamatrix identify
the registry entry, while an Ed25519 signature authenticates the SHA-256 digest
of the exact PDF bytes delivered to the user. Legacy KCEV1 rows remain readable
so previously distributed documents do not break during the transition.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from cryptography.exceptions import InvalidSignature
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.config import settings
from app.core.database import current_tenant_id
from app.models.document_issuance import DocumentIssuance
from app.services.document_seal_keys import (
    active_private_key as _active_private_key,
)
from app.services.document_seal_keys import (
    b64decode as _b64decode,
)
from app.services.document_seal_keys import (
    b64encode as _b64encode,
)
from app.services.document_seal_keys import (
    legacy_signing_key as _legacy_signing_key,
)
from app.services.document_seal_keys import (
    public_keyring as _public_keyring,
)
from app.services.document_seal_lineage import (
    IssuePolicy,
    SealFacts,
    issue_pending,
    lock_active_revisions,
    reject_if_newer_revision,
)
from app.services.pdf._cev import datamatrix_svg

DOCUMENT_TYPE_LABELS_FR: dict[str, str] = {
    "certificat_scolarite": "Certificat de scolarité",
    "attestation_frequentation": "Attestation de fréquentation",
    "bulletin": "Bulletin de notes",
}

SCHEME_LEGACY = "KCEV1"
SCHEME_CURRENT = "KSI2"
SIGNATURE_ALGORITHM = "Ed25519"
STATUS_PENDING = "pending"
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
STATUS_SUPERSEDED = "superseded"
STATUS_EXPIRED = "expired"
STATUS_FAILED = "failed"

_LEGACY_CODE_LEN = 12
_SEAL_CODE_BYTES = 10
_MAX_SEALED_PDF_BYTES = 20 * 1024 * 1024
_STALE_PENDING_AFTER = timedelta(minutes=5)


def _utcnow() -> datetime:
    """Return naive UTC for compatibility with the existing DATETIME columns."""
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


@dataclass(frozen=True)
class IssuedVerification:
    issuance_id: int
    token: str
    reference: str
    verify_url: str
    manual_verify_url: str
    seal_code: str
    datamatrix_svg: str
    sealed_pdf: bytes | None


def _legacy_payload(issuance: DocumentIssuance, tenant: str) -> bytes:
    parts = [
        SCHEME_LEGACY,
        tenant,
        issuance.document_type,
        issuance.reference,
        issuance.student_name,
        issuance.class_name or "",
        issuance.academic_year or "",
        issuance.issued_at.strftime("%Y-%m-%dT%H:%M:%S"),
    ]
    return "\x1f".join(parts).encode("utf-8")


def _current_payload(issuance: DocumentIssuance, tenant: str) -> bytes:
    if not issuance.document_sha256:
        raise ValueError("A finalized document digest is required")
    payload = {
        "academic_year": issuance.academic_year or "",
        "class_name": issuance.class_name or "",
        "document_sha256": issuance.document_sha256,
        "document_type": issuance.document_type,
        "expires_at": issuance.expires_at.isoformat(timespec="seconds")
        if issuance.expires_at
        else None,
        "issued_at": issuance.issued_at.isoformat(timespec="seconds"),
        "reference": issuance.reference,
        "revision": issuance.revision,
        "scheme": SCHEME_CURRENT,
        "source_sha256": issuance.source_sha256,
        "student_name": issuance.student_name,
        "tenant": tenant,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _legacy_code(signature: bytes) -> str:
    short = base64.b32encode(signature).decode("ascii").rstrip("=")[:_LEGACY_CODE_LEN]
    return "CEV-" + "-".join(short[index : index + 4] for index in range(0, len(short), 4))


def _new_seal_code() -> str:
    encoded = base64.b32encode(secrets.token_bytes(_SEAL_CODE_BYTES)).decode("ascii").rstrip("=")
    return "SNI-" + "-".join(encoded[index : index + 4] for index in range(0, 16, 4))


def _verify_url(token: str, tenant: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/verifier/{tenant}/{token}"


def _manual_verify_url(tenant: str) -> str:
    query = urlencode({"tenant": tenant})
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/verifier?{query}"


def _to_verification(issuance: DocumentIssuance, tenant: str) -> IssuedVerification:
    url = _verify_url(issuance.token, tenant)
    code = issuance.seal_code or issuance.cev_code
    return IssuedVerification(
        issuance_id=issuance.id,
        token=issuance.token,
        reference=issuance.reference,
        verify_url=url,
        manual_verify_url=_manual_verify_url(tenant),
        seal_code=code,
        datamatrix_svg=datamatrix_svg(url),
        sealed_pdf=issuance.pdf_content,
    )


async def issue_document(
    db: AsyncSession,
    *,
    document_type: str,
    reference: str,
    student_name: str,
    class_name: str | None = None,
    academic_year: str | None = None,
    student_id: int | None = None,
    issued_at: datetime | None = None,
    validity_days: int | None = None,
    source_sha256: str,
) -> IssuedVerification:
    """Create a pending KSI2 seal before the PDF is rendered."""
    tenant = current_tenant_id.get() or settings.LOCAL_TENANT_ID
    issued = (issued_at or _utcnow()).replace(microsecond=0)
    days = settings.DOCUMENT_SEAL_DEFAULT_VALIDITY_DAYS if validity_days is None else validity_days
    expires_at = issued + timedelta(days=days) if days > 0 else None

    facts = SealFacts(
        document_type=document_type,
        reference=reference,
        student_name=student_name,
        class_name=class_name,
        academic_year=academic_year,
        student_id=student_id,
        issued_at=issued,
        source_sha256=source_sha256,
    )
    issuance = await issue_pending(
        db,
        facts,
        policy=IssuePolicy(
            expires_at=expires_at,
            now=_utcnow(),
            stale_after=_STALE_PENDING_AFTER,
            scheme=SCHEME_CURRENT,
            signature_algorithm=SIGNATURE_ALGORITHM,
            key_id=settings.DOCUMENT_SEAL_ACTIVE_KEY_ID,
            statuses=(STATUS_PENDING, STATUS_ACTIVE, STATUS_FAILED),
        ),
        token_factory=lambda: secrets.token_urlsafe(32),
        code_factory=_new_seal_code,
        is_effectively_active=lambda row: effective_status(row) == STATUS_ACTIVE,
    )
    return _to_verification(issuance, tenant)


async def mark_document_failed(
    db: AsyncSession,
    issuance_id: int,
    *,
    reason: str,
) -> None:
    """Close a pending issuance so a later request can safely retry."""
    await db.rollback()
    issuance = await db.get(DocumentIssuance, issuance_id, with_for_update=True)
    if issuance is None or issuance.status != STATUS_PENDING:
        return
    issuance.status = STATUS_FAILED
    issuance.failed_at = _utcnow()
    issuance.failure_reason = reason.strip()[:500]
    await db.commit()


async def finalize_document(
    db: AsyncSession,
    issuance_id: int,
    pdf_bytes: bytes,
) -> DocumentIssuance:
    """Hash and sign the exact PDF bytes returned to the caller."""
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Only PDF documents can be sealed")
    if len(pdf_bytes) > _MAX_SEALED_PDF_BYTES:
        raise ValueError("The PDF exceeds the 20 MB sealing limit")
    tenant = current_tenant_id.get() or settings.LOCAL_TENANT_ID
    issuance = await db.get(DocumentIssuance, issuance_id, with_for_update=True)
    if issuance is None or issuance.scheme_version != SCHEME_CURRENT:
        raise ValueError("Unknown institutional seal issuance")

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    if issuance.status == STATUS_ACTIVE:
        if secrets.compare_digest(issuance.document_sha256 or "", digest):
            return issuance
        raise ValueError("A finalized issuance cannot be bound to different PDF bytes")
    if issuance.status != STATUS_PENDING:
        raise ValueError(f"Cannot finalize an issuance with status {issuance.status}")

    await reject_if_newer_revision(
        db,
        issuance,
        pending_status=STATUS_PENDING,
        active_status=STATUS_ACTIVE,
        superseded_status=STATUS_SUPERSEDED,
    )
    active_rows = await lock_active_revisions(db, issuance, active_status=STATUS_ACTIVE)

    issuance.document_sha256 = digest
    issuance.pdf_content = pdf_bytes
    issuance.pdf_size = len(pdf_bytes)
    issuance.signature = _b64encode(_active_private_key().sign(_current_payload(issuance, tenant)))
    issuance.status = STATUS_ACTIVE
    issuance.finalized_at = _utcnow()
    issuance.failed_at = None
    issuance.failure_reason = None

    for previous in active_rows:
        previous.superseded_by_id = issuance.id
        previous.status = STATUS_SUPERSEDED
    if active_rows and issuance.supersedes_id is None:
        issuance.supersedes_id = active_rows[0].id

    await db.commit()
    await db.refresh(issuance)
    return issuance


async def revoke_document(
    db: AsyncSession,
    issuance_id: int,
    *,
    reason: str,
    revoked_by: int,
) -> DocumentIssuance:
    from app.core.audit import AuditAction, audit_log

    normalized_reason = reason.strip()
    if len(normalized_reason) < 5:
        raise ValueError("A revocation reason of at least 5 characters is required")
    issuance = await db.get(DocumentIssuance, issuance_id, with_for_update=True)
    if issuance is None:
        raise ValueError("Unknown institutional seal issuance")
    if issuance.status not in {STATUS_ACTIVE, STATUS_EXPIRED}:
        raise ValueError(f"Cannot revoke an issuance with status {issuance.status}")
    issuance.status = STATUS_REVOKED
    issuance.revoked_at = _utcnow()
    issuance.revoked_by_id = revoked_by
    issuance.revocation_reason = normalized_reason[:500]
    await audit_log(
        db,
        entity_type="document_issuance",
        entity_id=issuance.id,
        action=AuditAction.UPDATE,
        user_id=revoked_by,
        old_values={"status": STATUS_ACTIVE},
        new_values={"status": STATUS_REVOKED, "reason": issuance.revocation_reason},
    )
    await db.commit()
    await db.refresh(issuance)
    return issuance


async def get_issuance_by_token(db: AsyncSession, token: str) -> DocumentIssuance | None:
    stmt = (
        select(DocumentIssuance)
        .options(defer(DocumentIssuance.pdf_content))
        .where(DocumentIssuance.token == token)
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _code_candidates(code: str) -> list[str]:
    compact = code.strip().upper().replace("-", "").replace(" ", "")
    for prefix in ("SNI", "CEV"):
        if compact.startswith(prefix):
            compact = compact[len(prefix) :]
            break
    if not compact:
        return []
    groups = "-".join(compact[index : index + 4] for index in range(0, len(compact), 4))
    return [f"SNI-{groups}", f"CEV-{groups}"]


async def get_issuance_by_code(db: AsyncSession, code: str) -> DocumentIssuance | None:
    candidates = _code_candidates(code)
    if not candidates:
        return None
    stmt = (
        select(DocumentIssuance)
        .options(defer(DocumentIssuance.pdf_content))
        .where(
            or_(
                DocumentIssuance.seal_code.in_(candidates),
                DocumentIssuance.cev_code.in_(candidates),
            )
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_issuance_by_cev_code(db: AsyncSession, code: str) -> DocumentIssuance | None:
    """Compatibility alias for callers using the former CEV terminology."""
    return await get_issuance_by_code(db, code)


def verify_signature(issuance: DocumentIssuance, *, tenant: str) -> bool:
    if issuance.scheme_version == SCHEME_LEGACY:
        expected = _legacy_code(_legacy_signing_key().sign(_legacy_payload(issuance, tenant)))
        return secrets.compare_digest(expected, issuance.cev_code)

    if (
        issuance.scheme_version != SCHEME_CURRENT
        or issuance.signature_algorithm != SIGNATURE_ALGORITHM
        or not issuance.key_id
        or not issuance.signature
        or not issuance.document_sha256
    ):
        return False

    public_key = _public_keyring().get(issuance.key_id)
    if public_key is None:
        return False
    try:
        public_key.verify(_b64decode(issuance.signature), _current_payload(issuance, tenant))
    except (InvalidSignature, ValueError):
        return False
    return True


def effective_status(issuance: DocumentIssuance, *, now: datetime | None = None) -> str:
    if issuance.status == STATUS_ACTIVE and issuance.expires_at:
        current = (now or _utcnow()).replace(microsecond=0)
        if current >= issuance.expires_at:
            return STATUS_EXPIRED
    return issuance.status


def verify_pdf_bytes(issuance: DocumentIssuance, pdf_bytes: bytes, *, tenant: str) -> bool:
    return verify_pdf_digest(issuance, hashlib.sha256(pdf_bytes).hexdigest(), tenant=tenant)


def matches_pdf_digest(issuance: DocumentIssuance, digest: str, *, tenant: str) -> bool:
    """Compare exact bytes independently from the seal lifecycle status."""
    return verify_signature(issuance, tenant=tenant) and secrets.compare_digest(
        issuance.document_sha256 or "", digest
    )


def verify_pdf_digest(issuance: DocumentIssuance, digest: str, *, tenant: str) -> bool:
    return effective_status(issuance) == STATUS_ACTIVE and matches_pdf_digest(
        issuance, digest, tenant=tenant
    )
