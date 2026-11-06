"""Export du suivi consolidé des échéanciers : périmètre, situation, document.

Le router ne fait que transmettre la demande. Ici se décident l'année et la
classe affichées sur le document, et le calcul est celui de l'écran : le même
`overview`, appelé sans pagination.
"""

from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.models.academic import AcademicYear, Class
from app.repositories.installment_overview_repository import COHORT_LIMIT
from app.schemas.installment_overview import ScheduleState
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.installments.overview import overview
from app.services.installments.overview_documents import (
    generate_overview_pdf,
    generate_overview_xlsx,
)

ExportFormat = Literal["pdf", "xlsx"]


async def _scope_labels(
    db: AsyncSession, academic_year_id: int, class_id: int | None
) -> tuple[str, str]:
    """Nom de l'année et de la classe, ou une erreur explicite si l'une manque."""
    year = (
        await db.execute(select(AcademicYear.name).where(AcademicYear.id == academic_year_id))
    ).scalar_one_or_none()
    if not year:
        raise BusinessValidationError("Année scolaire introuvable.")
    if class_id is None:
        return str(year), ""
    name = (await db.execute(select(Class.name).where(Class.id == class_id))).scalar_one_or_none()
    if name is None:
        raise BusinessValidationError("Classe introuvable.")
    return str(year), str(name)


async def export_overview(
    db: AsyncSession,
    *,
    academic_year_id: int,
    class_id: int | None,
    search: str,
    state: ScheduleState,
    export_format: ExportFormat,
) -> bytes:
    """Tous les résultats filtrés, pas seulement la page affichée.

    Le plafond de `COHORT_LIMIT` inscriptions est garanti par le dépôt, avec
    une erreur explicite au-delà : aucun export tronqué n'est présenté comme
    complet.
    """
    year, class_name = await _scope_labels(db, academic_year_id, class_id)
    data = await overview(
        db,
        academic_year_id=academic_year_id,
        class_id=class_id,
        search=search,
        state=state,
        page=1,
        size=COHORT_LIMIT,
    )
    school = await load_school_settings_for_pdf(db)
    options = {
        "year": year,
        "class_name": class_name,
        "search": search,
        "state": state,
        "issued_at": datetime.now(),
    }
    if export_format == "xlsx":
        return generate_overview_xlsx(data, school, **options)
    return generate_overview_pdf(data, school, **options)
