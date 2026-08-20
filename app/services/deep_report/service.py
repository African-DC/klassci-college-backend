"""Assemblage du rapport de fin de trimestre de la DEEP.

Charge le contexte une fois, laisse chaque chapitre produire ses tableaux,
puis rend le tout en PDF au gabarit officiel de l'établissement.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessValidationError
from app.services._school_settings_helper import load_school_settings_for_pdf
from app.services.deep_report import (
    chapter1_pedagogy,
    chapter1_recaps,
    chapter1_rosters,
    chapter2_gender,
    chapter2_movements,
    chapter2_pyramids,
    chapter3_admin,
    chapter3_teachers,
    chapter4_social,
)
from app.services.deep_report._context import load_context
from app.services.deep_report._types import DeepReport, ReportChapter
from app.services.pdf.deep_report import generate_deep_report_pdf

logger = logging.getLogger(__name__)

_CONCLUSION = (
    "Le présent rapport a été établi à partir des données enregistrées dans la "
    "plateforme de gestion de l'établissement à la date d'édition. Les tableaux "
    "portant la mention « à compléter manuellement » appellent des informations que "
    "la plateforme ne collecte pas : ils sont laissés vierges plutôt que remplis de "
    "valeurs nulles, une valeur nulle valant constat."
)


async def build_report(db: AsyncSession, academic_year_id: int, trimester: int) -> DeepReport:
    """Construit le rapport complet — 27 tableaux, quatre chapitres."""
    if trimester not in (1, 2, 3):
        raise BusinessValidationError("Le trimestre doit valoir 1, 2 ou 3.")

    context = await load_context(db, academic_year_id, trimester)

    results_chapter = ReportChapter(
        title="Chapitre I — B / Résultats scolaires",
        tables=(
            *chapter1_rosters.roster_tables(context),
            *chapter1_rosters.subsidised_roster_tables(context),
            *chapter1_recaps.build_tables(context),
            chapter1_rosters.top_students_table(context),
        ),
    )

    enrolment_chapter = ReportChapter(
        title="Chapitre II — Effectifs et pyramides",
        tables=(
            chapter2_movements.transfers_table(context),
            chapter2_movements.council_table(context),
            chapter2_pyramids.pyramid_table(context),
            chapter2_pyramids.birth_year_table(context),
            chapter2_movements.scholarships_table(context),
            *chapter2_gender.build_tables(context),
        ),
    )

    staff_chapter = ReportChapter(
        title="Chapitre III — Personnel",
        tables=(
            *chapter3_teachers.build_tables(context),
            *chapter3_admin.build_tables(context),
        ),
    )

    return DeepReport(
        academic_year_name=context.academic_year.name,
        trimester=trimester,
        chapters=[
            chapter1_pedagogy.build(context),
            results_chapter,
            enrolment_chapter,
            staff_chapter,
            chapter4_social.build(context),
        ],
        conclusion=_CONCLUSION,
    )


async def build_report_pdf(db: AsyncSession, academic_year_id: int, trimester: int) -> bytes:
    """Rapport DEEP au format PDF, habillé du thème de l'établissement."""
    report = await build_report(db, academic_year_id, trimester)
    school = await load_school_settings_for_pdf(db)
    pending = report.pending_table_numbers
    if pending:
        logger.info(
            "Rapport DEEP %s T%s : %d tableau(x) laissé(s) à compléter (%s)",
            academic_year_id,
            trimester,
            len(pending),
            ", ".join(str(number) for number in pending),
        )
    return generate_deep_report_pdf(report, school)
