"""Helpers partagés du Sceau numérique institutionnel KLASSCI.

Factorise l'appel à `document_issuance_service.issue_document` + la projection
en dict prêt pour les générateurs PDF (clés `reference`, `seal_code`,
`verify_url`, `cev_svg`). Chaque service calcule sa propre `reference`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

DOCUMENT_RENDER_VERSION = "2026-07-ksi2"
logger = logging.getLogger(__name__)


class VerificationPayload(TypedDict):
    issuance_id: int
    reference: str
    seal_code: str
    verify_url: str
    manual_verify_url: str
    cev_svg: str
    sealed_pdf: bytes | None


async def build_verification(
    db: AsyncSession,
    *,
    document_type: str,
    reference: str,
    student_name: str,
    class_name: str | None,
    academic_year: str | None,
    student_id: int | None,
    issued_at: datetime,
    source_data: object,
) -> VerificationPayload:
    """Crée un sceau en attente et renvoie le bloc prêt pour le PDF."""
    from app.services.document_issuance_service import issue_document

    issued = await issue_document(
        db,
        document_type=document_type,
        reference=reference,
        student_name=student_name,
        class_name=class_name or None,
        academic_year=academic_year or None,
        student_id=student_id,
        issued_at=issued_at,
        validity_days=0 if document_type == "bulletin" else None,
        source_sha256=hashlib.sha256(
            json.dumps(
                source_data,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=lambda value: (
                    value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)
                ),
            ).encode("utf-8")
        ).hexdigest(),
    )
    return {
        "issuance_id": issued.issuance_id,
        "reference": issued.reference,
        "seal_code": issued.seal_code,
        "verify_url": issued.verify_url,
        "manual_verify_url": issued.manual_verify_url,
        "cev_svg": issued.datamatrix_svg,
        "sealed_pdf": issued.sealed_pdf,
    }


async def finalize_verification(
    db: AsyncSession,
    verification: VerificationPayload,
    pdf_bytes: bytes,
) -> bytes:
    """Lie le sceau à l'empreinte du PDF final avant de retourner ses octets."""
    from app.services.document_issuance_service import finalize_document

    await finalize_document(db, verification["issuance_id"], pdf_bytes)
    return pdf_bytes


async def _mark_failed_safely(
    db: AsyncSession, verification: VerificationPayload, error: BaseException
) -> None:
    from app.services.document_issuance_service import mark_document_failed

    try:
        await mark_document_failed(
            db,
            verification["issuance_id"],
            reason=f"{type(error).__name__}: document rendering or sealing failed",
        )
    except Exception:
        logger.exception("Failed to close pending document seal %s", verification["issuance_id"])


async def render_verification(
    db: AsyncSession,
    verification: VerificationPayload,
    renderer: Callable[[], bytes],
) -> bytes:
    """Render and finalize a PDF, closing the pending seal on any failure."""
    if sealed_pdf := verification.get("sealed_pdf"):
        return sealed_pdf

    try:
        return await finalize_verification(db, verification, renderer())
    except BaseException as exc:
        cleanup = asyncio.create_task(_mark_failed_safely(db, verification, exc))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
        raise
