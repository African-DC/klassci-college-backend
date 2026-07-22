"""Public verification of KLASSCI institutional document seals."""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db
from app.models.document_issuance import DocumentIssuance
from app.schemas.public_verify import (
    PublicFileVerificationResponse,
    PublicFileVerificationUnavailableResponse,
    PublicVerificationErrorResponse,
    PublicVerificationResponse,
    PublicVerificationSchema,
)
from app.services import document_issuance_service as svc
from app.services._school_settings_helper import load_school_settings_for_pdf

router = APIRouter(prefix="/public", tags=["public"])

_PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store, private",
}
_MAX_PDF_BYTES = 20 * 1024 * 1024
_UPLOAD_SLOTS = asyncio.Semaphore(4)


def _public_response(payload: PublicVerificationSchema, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=_PUBLIC_HEADERS,
    )


def _not_found() -> JSONResponse:
    return _public_response(
        PublicVerificationErrorResponse(detail="Document not found", code="NOT_FOUND"),
        status_code=404,
    )


async def _build_response(
    db: AsyncSession, issuance: DocumentIssuance | None, tenant: str
) -> JSONResponse:
    if issuance is None or not svc.verify_signature(issuance, tenant=tenant):
        return _not_found()

    status = svc.effective_status(issuance)
    if status in {svc.STATUS_PENDING, svc.STATUS_FAILED}:
        return _not_found()

    school = await load_school_settings_for_pdf(db)
    return _public_response(
        PublicVerificationResponse(
            valid=status == svc.STATUS_ACTIVE,
            status=status,
            scheme=issuance.scheme_version,
            document_type=svc.DOCUMENT_TYPE_LABELS_FR.get(
                issuance.document_type, issuance.document_type
            ),
            issued_at=issuance.issued_at,
            expires_at=issuance.expires_at,
            school_name=school.get("school_name") or "",
            signature_algorithm=issuance.signature_algorithm,
            key_id=issuance.key_id,
            file_verification_available=bool(issuance.document_sha256),
        )
    )


@router.get(
    "/verify/{tenant}/{token}",
    response_model=PublicVerificationResponse,
    responses={404: {"model": PublicVerificationErrorResponse}},
)
async def verify_by_token(
    tenant: str,
    token: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    issuance = await svc.get_issuance_by_token(db, token)
    return await _build_response(db, issuance, tenant)


@router.get(
    "/verify-code/{tenant}/{seal_code}",
    response_model=PublicVerificationResponse,
    responses={404: {"model": PublicVerificationErrorResponse}},
)
async def verify_by_seal_code(
    tenant: str,
    seal_code: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    issuance = await svc.get_issuance_by_code(db, seal_code)
    return await _build_response(db, issuance, tenant)


async def _verify_uploaded_file(
    issuance: DocumentIssuance | None,
    tenant: str,
    document: UploadFile,
) -> JSONResponse:
    if issuance is None or not svc.verify_signature(issuance, tenant=tenant):
        return _not_found()
    if not issuance.document_sha256:
        document_status = svc.effective_status(issuance)
        return _public_response(
            PublicFileVerificationUnavailableResponse(
                valid=False,
                matches=False,
                status="unavailable",
                code="FILE_VERIFICATION_UNAVAILABLE",
                signature_valid=True,
                document_status=document_status,
            ),
            status_code=409,
        )

    async with _UPLOAD_SLOTS:
        digest = hashlib.sha256()
        total = 0
        first_chunk = True
        while chunk := await document.read(1024 * 1024):
            if first_chunk and not chunk.startswith(b"%PDF-"):
                return _public_response(
                    PublicVerificationErrorResponse(detail="Invalid PDF", code="INVALID_PDF"),
                    status_code=422,
                )
            first_chunk = False
            total += len(chunk)
            if total > _MAX_PDF_BYTES:
                return _public_response(
                    PublicVerificationErrorResponse(detail="PDF too large", code="FILE_TOO_LARGE"),
                    status_code=413,
                )
            digest.update(chunk)

        if total == 0:
            return _public_response(
                PublicVerificationErrorResponse(detail="Invalid PDF", code="INVALID_PDF"),
                status_code=422,
            )

    document_status = svc.effective_status(issuance)
    matches = svc.matches_pdf_digest(issuance, digest.hexdigest(), tenant=tenant)
    return _public_response(
        PublicFileVerificationResponse(
            valid=matches and document_status == svc.STATUS_ACTIVE,
            matches=matches,
            status="matching" if matches else "modified",
            signature_valid=True,
            document_status=document_status,
        )
    )


@router.post(
    "/verify-file/{tenant}/{token}",
    response_model=PublicFileVerificationResponse,
    responses={
        404: {"model": PublicVerificationErrorResponse},
        409: {"model": PublicFileVerificationUnavailableResponse},
        413: {"model": PublicVerificationErrorResponse},
        422: {"model": PublicVerificationErrorResponse},
    },
)
async def verify_file_by_token(
    tenant: str,
    token: str,
    document: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    issuance = await svc.get_issuance_by_token(db, token)
    return await _verify_uploaded_file(issuance, tenant, document)


@router.post(
    "/verify-file-code/{tenant}/{seal_code}",
    response_model=PublicFileVerificationResponse,
    responses={
        404: {"model": PublicVerificationErrorResponse},
        409: {"model": PublicFileVerificationUnavailableResponse},
        413: {"model": PublicVerificationErrorResponse},
        422: {"model": PublicVerificationErrorResponse},
    },
)
async def verify_file_by_code(
    tenant: str,
    seal_code: str,
    document: UploadFile = File(...),
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    issuance = await svc.get_issuance_by_code(db, seal_code)
    return await _verify_uploaded_file(issuance, tenant, document)
