"""Tâche Celery — génération asynchrone des bulletins PDF."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import _get_session_factory, current_tenant_id

logger = logging.getLogger(__name__)

_SAFE_URL_RE = re.compile(
    r"^https://[\w\-]+\.digitaloceanspaces\.com/[\w\-/%.]+\.pdf$", re.IGNORECASE
)


@celery_app.task(bind=True, name="grades.generate_bulletins")  # type: ignore[misc]
def generate_bulletins_task(
    self: Any,
    tenant_id: str,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> dict[str, Any]:
    """Génère les bulletins PDF via Puppeteer et les stocke sur DO Spaces."""
    try:
        result = asyncio.run(
            _generate_async(
                tenant_id=tenant_id,
                class_id=class_id,
                trimester=trimester,
                academic_year_id=academic_year_id,
            )
        )
        return {"bulletin_urls": result}
    except Exception as exc:
        logger.exception(
            "Bulletin generation failed for tenant=%s class=%s trimester=%s",
            tenant_id,
            class_id,
            trimester,
        )
        raise exc


async def _generate_async(
    tenant_id: str,
    class_id: int,
    trimester: int,
    academic_year_id: int,
) -> list[str]:
    from app.repositories import grades_repository as repo

    current_tenant_id.set(tenant_id)
    factory = await _get_session_factory(tenant_id)

    async with factory() as db:
        # Calculer les moyennes et rangs
        summary = await repo.get_grades_summary(db, class_id, trimester, academic_year_id)
        students_data = summary["students"]

        if not students_data:
            return []

        bulletin_urls: list[str] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for student_summary in students_data:
                student_id = student_summary["student_id"]

                # Préparer les données pour Puppeteer
                payload = {
                    "tenant_id": tenant_id,
                    "student_id": student_id,
                    "student_name": student_summary["student_name"],
                    "class_id": class_id,
                    "academic_year_id": academic_year_id,
                    "trimester": trimester,
                    "average": float(student_summary["average"])
                    if student_summary["average"]
                    else None,
                    "rank": student_summary["rank"],
                    "mention": student_summary["mention"],
                    "subjects": [
                        {
                            "subject_id": s["subject_id"],
                            "subject_name": s["subject_name"],
                            "class_average": float(s["class_average"])
                            if s["class_average"]
                            else None,
                        }
                        for s in summary["subjects"]
                    ],
                }

                try:
                    response = await client.post(
                        f"{settings.PUPPETEER_URL}/generate-bulletin",
                        json=payload,
                    )
                    response.raise_for_status()
                    pdf_data = response.json()
                    raw_url = pdf_data.get("url", "")
                    # Valider l'URL pour éviter les URLs malicieuses du service Puppeteer
                    file_url = raw_url if _SAFE_URL_RE.match(raw_url) else None
                    if raw_url and not file_url:
                        logger.warning(
                            "Puppeteer returned invalid URL for student=%s: %r", student_id, raw_url
                        )
                except httpx.HTTPError as exc:
                    logger.warning("Puppeteer failed for student=%s: %s", student_id, exc)
                    file_url = None

                # Upsert bulletin en DB
                await repo.upsert_bulletin(
                    db,
                    student_id=student_id,
                    class_id=class_id,
                    academic_year_id=academic_year_id,
                    trimester=trimester,
                    average=student_summary["average"],
                    rank=student_summary["rank"],
                    mention=student_summary["mention"],
                    file_url=file_url,
                )

                if file_url:
                    bulletin_urls.append(file_url)

        await db.commit()
        return bulletin_urls
