"""Rapport de fin de trimestre de la DEEP — 27 tableaux, quatre chapitres.

Point d'entrée : `build_report_pdf(db, academic_year_id, trimester)`.
"""

from app.services.deep_report.service import build_report, build_report_pdf

__all__ = ["build_report", "build_report_pdf"]
