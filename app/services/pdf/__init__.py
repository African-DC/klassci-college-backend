"""Package PDF — service splitté par template + design system commun.

| Sub-module | Document |
|------------|----------|
| `theme` | Constantes palette KLASSCI, status labels, méthode paiement |
| `_helpers` | `_esc`, `_format_decimal`, `_image_to_datauri`, headers/footers officiels |
| `bulletin` | Bulletin de notes trimestre élève |
| `council_minutes` | PV conseil de classe (landscape A4) |
| `receipt` | Reçu de paiement avec breakdown allocation |
| `timetable` | Emploi du temps (landscape A4 grille horaire) |
| `certificate_scolarite` | Certificat de scolarité officiel CI |
| `attendance_certificate` | Attestation de fréquentation officielle CI |
| `fee_statement` | État individuel des frais (NEW P0) |
| `deep_report` | Rapport de fin de trimestre DEEP, 27 tableaux (landscape A4) |

Call sites historiques `from app.services.pdf_service import generate_X_pdf`
passent par la facade `pdf_service.py` qui re-exporte tout.
"""

from app.services.pdf import components
from app.services.pdf._helpers import (
    _BASE_STYLES,
    _CI_HEADER,
    _esc,
    _format_decimal,
    _image_to_datauri,
    _official_footer_html,
    _school_header_html,
    enum_value,
)
from app.services.pdf.attendance_certificate import generate_attendance_certificate_pdf
from app.services.pdf.attendance_sheet import generate_attendance_sheet_pdf
from app.services.pdf.bulletin import generate_bulletin_pdf
from app.services.pdf.cahier_texte import generate_cahier_texte_pdf
from app.services.pdf.certificate_scolarite import generate_certificate_scolarite_pdf
from app.services.pdf.class_roster import generate_class_roster_pdf
from app.services.pdf.class_synthesis import generate_class_synthesis_pdf
from app.services.pdf.council_minutes import generate_council_minutes_pdf
from app.services.pdf.daily_cash_book import generate_daily_cash_book_pdf
from app.services.pdf.enrollment_form import generate_enrollment_form_pdf
from app.services.pdf.fee_statement import generate_fee_statement_pdf
from app.services.pdf.grade_report import generate_grade_report_pdf
from app.services.pdf.grade_sheet import generate_grade_sheet_pdf
from app.services.pdf.receipt import generate_receipt_pdf
from app.services.pdf.theme import _ACCENT, _PRIMARY, PDFTheme, method_label, status_label
from app.services.pdf.timetable import generate_timetable_pdf

__all__ = [
    "_ACCENT",
    "_BASE_STYLES",
    "_CI_HEADER",
    "_PRIMARY",
    "_esc",
    "_format_decimal",
    "_image_to_datauri",
    "_official_footer_html",
    "_school_header_html",
    "PDFTheme",
    "components",
    "enum_value",
    "generate_attendance_certificate_pdf",
    "generate_attendance_sheet_pdf",
    "generate_bulletin_pdf",
    "generate_cahier_texte_pdf",
    "generate_certificate_scolarite_pdf",
    "generate_class_roster_pdf",
    "generate_class_synthesis_pdf",
    "generate_council_minutes_pdf",
    "generate_daily_cash_book_pdf",
    "generate_enrollment_form_pdf",
    "generate_fee_statement_pdf",
    "generate_grade_report_pdf",
    "generate_grade_sheet_pdf",
    "generate_receipt_pdf",
    "generate_timetable_pdf",
    "method_label",
    "status_label",
]
