"""Helper partagé : émission du Cachet Électronique Visible pour un document.

Factorise l'appel à `document_issuance_service.issue_document` + la projection
en dict prêt pour les générateurs PDF (clés `reference`, `cev_code`,
`verify_url`, `cev_svg`). Chaque service calcule sa propre `reference`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


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
) -> dict[str, Any]:
    """Émet le CEV et renvoie le bloc prêt pour `premium_footer`."""
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
    )
    return {
        "reference": issued.reference,
        "cev_code": issued.cev_code,
        "verify_url": issued.verify_url,
        "cev_svg": issued.datamatrix_svg,
    }
