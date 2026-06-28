"""Vérification publique d'authenticité des documents officiels (CEV).

Routes NON authentifiées : un parent / employeur scanne le Datamatrix du
Cachet Électronique Visible (qui ouvre `/verifier/{tenant}/{token}`) ou saisit
le code CEV lisible. Le tenant est porté par l'URL (le TenantMiddleware le
résout depuis le path pour ces routes).

Le jeton fait 256 bits (non énumérable) ; la signature Ed25519 est revérifiée
à chaque appel pour détecter toute falsification des données imprimées.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_tenant_db
from app.models.document_issuance import DocumentIssuance
from app.services import document_issuance_service as svc
from app.services._school_settings_helper import load_school_settings_for_pdf

router = APIRouter(prefix="/public", tags=["public"])

_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


async def _build_response(
    db: AsyncSession, issuance: DocumentIssuance | None, tenant: str
) -> JSONResponse:
    """Réponse JSON commune (noindex) — 404 si introuvable ou signature invalide."""
    if issuance is None or not svc.verify_signature(issuance, tenant=tenant):
        return JSONResponse(
            status_code=404,
            content={"detail": "Document not found", "code": "NOT_FOUND"},
            headers=_NOINDEX,
        )

    school = await load_school_settings_for_pdf(db)
    payload: dict[str, Any] = {
        "valid": True,
        "document_type": svc.DOCUMENT_TYPE_LABELS_FR.get(
            issuance.document_type, issuance.document_type
        ),
        "reference": issuance.reference,
        "student_name": issuance.student_name,
        "class_name": issuance.class_name,
        "academic_year": issuance.academic_year,
        "issued_at": issuance.issued_at.isoformat() if issuance.issued_at else None,
        "school_name": school.get("school_name") or "",
    }
    return JSONResponse(content=payload, headers=_NOINDEX)


@router.get("/verify/{tenant}/{token}")
async def verify_by_token(
    tenant: str,
    token: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    """Vérifie un document via son jeton (encodé dans le Datamatrix scanné)."""
    issuance = await svc.get_issuance_by_token(db, token)
    return await _build_response(db, issuance, tenant)


@router.get("/verify-code/{tenant}/{cev_code}")
async def verify_by_cev_code(
    tenant: str,
    cev_code: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> JSONResponse:
    """Vérifie un document via le code CEV lisible saisi à la main."""
    issuance = await svc.get_issuance_by_cev_code(db, cev_code)
    return await _build_response(db, issuance, tenant)
