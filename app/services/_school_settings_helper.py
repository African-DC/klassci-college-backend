"""Helper unique pour le dict school_settings consommé par les generators PDF.

Une seule source de vérité — quand un field est ajouté à SchoolSettings,
il apparaît automatiquement dans le dict sans rien éditer côté compositors.

Voir rule `.claude/rules/audit-school-settings-compositors.md` pour le
contexte (bug latent fondateur 2026-05-18).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import SchoolSettings

# Champs jamais exposés au PDF (compteurs internes, timestamps, etc.).
# Tout le reste passe automatiquement.
_PDF_EXCLUDE = {
    "id",
    "enrollment_number_counter",
    "enrollment_number_pattern",
    "slot_duration_minutes",
    "day_start_hour",
    "day_end_hour",
    "created_at",
    "updated_at",
    # MailPulse — config technique et secrets, jamais dans un PDF.
    "mailpulse_enabled",
    "mailpulse_base_url",
    "mailpulse_api_key",
    "mailpulse_sender_email",
    "mailpulse_sender_name",
    "mailpulse_default_language",
    "mailpulse_timeout",
    "mailpulse_real_workflows_enabled",
    "mailpulse_test_email_enabled",
    "mailpulse_test_whatsapp_enabled",
    "mailpulse_test_email_recipients",
    "mailpulse_test_phone_recipients",
    "mailpulse_inbound_secret",
}


async def load_school_settings_for_pdf(db: AsyncSession) -> dict[str, Any]:
    """Renvoie le singleton SchoolSettings projeté en dict pour les compositors PDF.

    Inclut toutes les colonnes pertinentes (school_name, ministry_code, address,
    phone, email, logo_url, signature_image_url, head_master_name,
    head_master_title, primary_color, accent_color, website, motto, ...).

    Fallback `{"school_name": "Etablissement"}` si fresh tenant sans row.
    """
    stmt = select(SchoolSettings).limit(1)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        return {"school_name": "Etablissement"}
    return {
        col.name: getattr(settings, col.name)
        for col in SchoolSettings.__table__.columns
        if col.name not in _PDF_EXCLUDE
    }
