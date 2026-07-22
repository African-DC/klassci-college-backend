"""Transactional lineage operations for institutional document seals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.document_issuance import DocumentIssuance


@dataclass(frozen=True)
class SealFacts:
    document_type: str
    reference: str
    student_name: str
    class_name: str | None
    academic_year: str | None
    student_id: int | None
    issued_at: datetime
    source_sha256: str

    def matches(self, issuance: DocumentIssuance) -> bool:
        same = (
            issuance.document_type == self.document_type
            and issuance.student_name == self.student_name
            and issuance.class_name == self.class_name
            and issuance.academic_year == self.academic_year
            and issuance.source_sha256 == self.source_sha256
        )
        return same and (self.document_type != "bulletin" or issuance.issued_at == self.issued_at)


@dataclass(frozen=True)
class IssuePolicy:
    expires_at: datetime | None
    now: datetime
    stale_after: timedelta
    scheme: str
    signature_algorithm: str
    key_id: str
    statuses: tuple[str, str, str]


async def _lock_lineage(db: AsyncSession, facts: SealFacts) -> list[DocumentIssuance]:
    stmt = (
        select(DocumentIssuance)
        .where(
            DocumentIssuance.document_type == facts.document_type,
            DocumentIssuance.reference == facts.reference,
        )
        .order_by(DocumentIssuance.revision.desc(), DocumentIssuance.id.desc())
        .with_for_update()
    )
    return list((await db.execute(stmt)).scalars().all())


def _reusable_active(
    lineage: list[DocumentIssuance],
    facts: SealFacts,
    *,
    current_scheme: str,
    active_status: str,
    is_effectively_active: Callable[[DocumentIssuance], bool],
) -> DocumentIssuance | None:
    active = next(
        (
            row
            for row in lineage
            if row.scheme_version == current_scheme and row.status == active_status
        ),
        None,
    )
    if active and active.pdf_content and is_effectively_active(active) and facts.matches(active):
        return active
    return None


def _guard_pending(
    lineage: list[DocumentIssuance],
    *,
    current_scheme: str,
    pending_status: str,
    failed_status: str,
    now: datetime,
    stale_after: timedelta,
) -> None:
    pending = next((row for row in lineage if row.status == pending_status), None)
    if pending is None or pending.scheme_version != current_scheme:
        return
    created_at = pending.created_at or pending.issued_at
    if created_at > now - stale_after:
        raise BusinessValidationError(
            "La génération de ce document est déjà en cours. Réessayez dans quelques secondes."
        )
    pending.status = failed_status
    pending.failed_at = now
    pending.failure_reason = "Generation interrupted before finalization"


def _new_pending(
    facts: SealFacts,
    *,
    token: str,
    seal_code: str,
    scheme: str,
    signature_algorithm: str,
    key_id: str,
    revision: int,
    expires_at: datetime | None,
    pending_status: str,
    supersedes_id: int | None,
) -> DocumentIssuance:
    return DocumentIssuance(
        token=token,
        cev_code=seal_code,
        seal_code=seal_code,
        document_type=facts.document_type,
        reference=facts.reference,
        student_name=facts.student_name,
        class_name=facts.class_name,
        academic_year=facts.academic_year,
        student_id=facts.student_id,
        issued_at=facts.issued_at,
        scheme_version=scheme,
        signature_algorithm=signature_algorithm,
        key_id=key_id,
        source_sha256=facts.source_sha256,
        status=pending_status,
        revision=revision,
        expires_at=expires_at,
        supersedes_id=supersedes_id,
    )


async def _persist_pending(db: AsyncSession, issuance: DocumentIssuance) -> DocumentIssuance | None:
    db.add(issuance)
    try:
        await db.commit()
        await db.refresh(issuance)
        return issuance
    except IntegrityError:
        await db.rollback()
        return None


async def issue_pending(
    db: AsyncSession,
    facts: SealFacts,
    *,
    policy: IssuePolicy,
    token_factory: Callable[[], str],
    code_factory: Callable[[], str],
    is_effectively_active: Callable[[DocumentIssuance], bool],
) -> DocumentIssuance:
    pending_status, active_status, failed_status = policy.statuses
    for _ in range(5):
        lineage = await _lock_lineage(db, facts)
        reusable = _reusable_active(
            lineage,
            facts,
            current_scheme=policy.scheme,
            active_status=active_status,
            is_effectively_active=is_effectively_active,
        )
        if reusable:
            return reusable
        _guard_pending(
            lineage,
            current_scheme=policy.scheme,
            pending_status=pending_status,
            failed_status=failed_status,
            now=policy.now,
            stale_after=policy.stale_after,
        )
        previous = lineage[0] if lineage else None
        active = next((row for row in lineage if row.status == active_status), None)
        issuance = _new_pending(
            facts,
            token=token_factory(),
            seal_code=code_factory(),
            scheme=policy.scheme,
            signature_algorithm=policy.signature_algorithm,
            key_id=policy.key_id,
            revision=previous.revision + 1 if previous else 1,
            expires_at=policy.expires_at,
            pending_status=pending_status,
            supersedes_id=active.id if active else None,
        )
        if persisted := await _persist_pending(db, issuance):
            return persisted
    raise RuntimeError("Unable to allocate a unique institutional seal code")


async def reject_if_newer_revision(
    db: AsyncSession,
    issuance: DocumentIssuance,
    *,
    pending_status: str,
    active_status: str,
    superseded_status: str,
) -> None:
    stmt = (
        select(DocumentIssuance)
        .where(
            DocumentIssuance.document_type == issuance.document_type,
            DocumentIssuance.reference == issuance.reference,
            DocumentIssuance.revision > issuance.revision,
            DocumentIssuance.status.in_((pending_status, active_status)),
        )
        .order_by(DocumentIssuance.revision.desc())
        .with_for_update()
        .limit(1)
    )
    newer = (await db.execute(stmt)).scalar_one_or_none()
    if newer is None:
        return
    issuance.status = superseded_status
    issuance.superseded_by_id = newer.id
    await db.commit()
    raise BusinessValidationError(
        "Une révision plus récente de ce document est déjà en cours de traitement."
    )


async def lock_active_revisions(
    db: AsyncSession,
    issuance: DocumentIssuance,
    *,
    active_status: str,
) -> list[DocumentIssuance]:
    stmt = (
        select(DocumentIssuance)
        .where(
            DocumentIssuance.document_type == issuance.document_type,
            DocumentIssuance.reference == issuance.reference,
            DocumentIssuance.status == active_status,
            DocumentIssuance.id != issuance.id,
        )
        .with_for_update()
    )
    return list((await db.execute(stmt)).scalars().all())
