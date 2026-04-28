"""Service PDF — generation de bulletins, PV de conseil et reçus de paiement.

WeasyPrint est importé paresseusement (à l'intérieur de chaque fonction qui
l'utilise) pour permettre au BE de booter sur Windows sans GTK installé. Les
endpoints PDF crashent à l'appel et non au boot, ce qui est acceptable car
en dev local on a rarement besoin des PDF.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared header / styles
# ---------------------------------------------------------------------------

_CI_HEADER = """
<div style="text-align:center; margin-bottom:10px;">
    <div style="font-size:11px; text-transform:uppercase;">
        Republique de Cote d'Ivoire
    </div>
    <div style="font-size:10px; font-style:italic; margin-bottom:4px;">
        Union &mdash; Discipline &mdash; Travail
    </div>
    <div style="font-size:10px;">
        Ministere de l'Education Nationale et de l'Alphabetisation
    </div>
</div>
"""

_BASE_STYLES = """
<style>
    @page { margin: 15mm; }
    body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 11px; color: #222; }
    h1 { font-size: 16px; text-align: center; margin: 10px 0; }
    h2 { font-size: 13px; margin: 8px 0; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0; }
    th, td { border: 1px solid #555; padding: 4px 6px; text-align: left; font-size: 10px; }
    th { background: #e9e9e9; font-weight: bold; }
    .text-center { text-align: center; }
    .text-right { text-align: right; }
    .school-header { text-align: center; margin-bottom: 8px; }
    .school-name { font-size: 14px; font-weight: bold; }
    .ministry-code { font-size: 10px; color: #555; }
    .signatures { display: flex; justify-content: space-between; margin-top: 30px; }
    .signature-block { text-align: center; width: 30%; }
    .signature-line { border-top: 1px solid #333; margin-top: 40px; padding-top: 4px; }
    .info-row { margin: 3px 0; font-size: 11px; }
    .mention-badge { font-weight: bold; padding: 2px 8px; border-radius: 3px; }
</style>
"""


def _school_header_html(school_name: str, ministry_code: str | None) -> str:
    code_line = ""
    if ministry_code:
        code_line = f'<div class="ministry-code">Code : {_esc(ministry_code)}</div>'
    return f"""
    {_CI_HEADER}
    <div class="school-header">
        <div class="school-name">{_esc(school_name)}</div>
        {code_line}
    </div>
    """


def _esc(val: Any) -> str:
    """Escape HTML characters."""
    if val is None:
        return ""
    return (
        str(val)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_decimal(val: Decimal | None) -> str:
    if val is None:
        return "-"
    return f"{val:.2f}"


# ---------------------------------------------------------------------------
# Bulletin PDF
# ---------------------------------------------------------------------------


def generate_bulletin_pdf(bulletin_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Generate a PDF bulletin for a single student.

    bulletin_data keys:
        student_name, class_name, trimester, academic_year_name,
        average, rank, total_students, mention, council_decision,
        teacher_comment, subject_averages (list of dicts with
        subject_name, average, coefficient), generated_at

    school_settings keys:
        school_name, ministry_code
    """
    school_name = school_settings.get("school_name", "Etablissement")
    ministry_code = school_settings.get("ministry_code")

    student_name = _esc(bulletin_data.get("student_name", ""))
    class_name = _esc(bulletin_data.get("class_name", ""))
    trimester = bulletin_data.get("trimester", "")
    academic_year = _esc(bulletin_data.get("academic_year_name", ""))
    average = _format_decimal(bulletin_data.get("average"))
    rank = bulletin_data.get("rank")
    total_students = bulletin_data.get("total_students", 0)
    mention = _esc(bulletin_data.get("mention", ""))
    council_decision = _esc(bulletin_data.get("council_decision", ""))
    teacher_comment = _esc(bulletin_data.get("teacher_comment", ""))
    subject_averages = bulletin_data.get("subject_averages", [])
    generated_at = bulletin_data.get("generated_at")

    rank_display = f"{rank}/{total_students}" if rank else "-"
    gen_date = generated_at.strftime("%d/%m/%Y") if isinstance(generated_at, datetime) else ""

    # Build subject rows
    subject_rows = ""
    for sa in subject_averages:
        subject_rows += f"""
        <tr>
            <td>{_esc(sa.get("subject_name", ""))}</td>
            <td class="text-center">{_format_decimal(sa.get("average"))}</td>
            <td class="text-center">{sa.get("coefficient", 1)}</td>
        </tr>
        """

    # Council decision row (only for T3)
    decision_section = ""
    if council_decision:
        decision_section = f"""
        <div class="info-row"><strong>Decision du conseil :</strong> {council_decision}</div>
        """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{_BASE_STYLES}</head>
    <body>
        {_school_header_html(school_name, ministry_code)}

        <h1>BULLETIN DE NOTES &mdash; Trimestre {trimester}</h1>

        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
            <div>
                <div class="info-row"><strong>Eleve :</strong> {student_name}</div>
                <div class="info-row"><strong>Classe :</strong> {class_name}</div>
            </div>
            <div>
                <div class="info-row"><strong>Annee scolaire :</strong> {academic_year}</div>
                <div class="info-row"><strong>Date :</strong> {gen_date}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Matiere</th>
                    <th class="text-center" style="width:80px;">Moyenne / 20</th>
                    <th class="text-center" style="width:80px;">Coefficient</th>
                </tr>
            </thead>
            <tbody>
                {subject_rows}
            </tbody>
        </table>

        <div style="margin-top: 12px; padding: 8px; border: 1px solid #555; background: #f5f5f5;">
            <div class="info-row"><strong>Moyenne generale :</strong> {average} / 20</div>
            <div class="info-row"><strong>Rang :</strong> {rank_display}</div>
            <div class="info-row"><strong>Mention :</strong> {mention}</div>
            {decision_section}
        </div>

        {"<div style='margin-top:10px;'><strong>Appreciation du professeur principal :</strong><br/>" + teacher_comment + "</div>" if teacher_comment else ""}

        <div style="display: flex; justify-content: space-between; margin-top: 40px;">
            <div style="text-align:center; width:30%;">
                <div>Le Professeur Principal</div>
                <div style="border-top:1px solid #333; margin-top:40px; padding-top:4px;"></div>
            </div>
            <div style="text-align:center; width:30%;">
                <div>Le Parent / Tuteur</div>
                <div style="border-top:1px solid #333; margin-top:40px; padding-top:4px;"></div>
            </div>
            <div style="text-align:center; width:30%;">
                <div>Le Chef d'Etablissement</div>
                <div style="border-top:1px solid #333; margin-top:40px; padding-top:4px;"></div>
            </div>
        </div>
    </body>
    </html>
    """

    from weasyprint import HTML  # lazy import — see module docstring

    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Council Minutes PDF
# ---------------------------------------------------------------------------


def generate_council_minutes_pdf(
    council_data: dict[str, Any], school_settings: dict[str, Any]
) -> bytes:
    """Generate a landscape A4 PDF for the council minutes (PV).

    council_data keys:
        class_name, trimester, academic_year_name,
        main_teacher_name, director_name, dren_name, notes,
        generated_at, decisions (list of dicts with
        student_name, average, rank, absence_count,
        auto_decision, final_decision, override_reason)

    school_settings keys:
        school_name, ministry_code
    """
    school_name = school_settings.get("school_name", "Etablissement")
    ministry_code = school_settings.get("ministry_code")

    class_name = _esc(council_data.get("class_name", ""))
    trimester = council_data.get("trimester", "")
    academic_year = _esc(council_data.get("academic_year_name", ""))
    main_teacher = _esc(council_data.get("main_teacher_name", ""))
    director = _esc(council_data.get("director_name", ""))
    dren = _esc(council_data.get("dren_name", ""))
    notes = _esc(council_data.get("notes", ""))
    generated_at = council_data.get("generated_at")
    decisions = council_data.get("decisions", [])

    gen_date = generated_at.strftime("%d/%m/%Y") if isinstance(generated_at, datetime) else ""
    total_students = len(decisions)

    # Stats
    passage_count = sum(
        1 for d in decisions if (d.get("final_decision") or d.get("auto_decision")) == "passage"
    )
    redoublement_count = sum(
        1
        for d in decisions
        if (d.get("final_decision") or d.get("auto_decision")) == "redoublement"
    )
    exclusion_count = sum(
        1 for d in decisions if (d.get("final_decision") or d.get("auto_decision")) == "exclusion"
    )
    repechage_count = sum(
        1 for d in decisions if (d.get("final_decision") or d.get("auto_decision")) == "repechage"
    )

    # Decision rows
    decision_rows = ""
    for i, d in enumerate(decisions, 1):
        final = d.get("final_decision") or d.get("auto_decision", "")
        override = _esc(d.get("override_reason", ""))
        decision_rows += f"""
        <tr>
            <td class="text-center">{i}</td>
            <td>{_esc(d.get("student_name", ""))}</td>
            <td class="text-center">{_format_decimal(d.get("average"))}</td>
            <td class="text-center">{d.get("rank", "-") or "-"}</td>
            <td class="text-center">{d.get("absence_count", 0)}</td>
            <td class="text-center">{_esc(d.get("auto_decision", ""))}</td>
            <td class="text-center">{_esc(final)}</td>
            <td>{override}</td>
        </tr>
        """

    landscape_style = """
    <style>
        @page { size: A4 landscape; margin: 12mm; }
        body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 10px; color: #222; }
        h1 { font-size: 15px; text-align: center; margin: 8px 0; }
        table { width: 100%; border-collapse: collapse; margin: 6px 0; }
        th, td { border: 1px solid #555; padding: 3px 5px; text-align: left; font-size: 9px; }
        th { background: #e9e9e9; font-weight: bold; }
        .text-center { text-align: center; }
        .text-right { text-align: right; }
        .school-header { text-align: center; margin-bottom: 6px; }
        .school-name { font-size: 13px; font-weight: bold; }
        .ministry-code { font-size: 9px; color: #555; }
        .info-row { margin: 2px 0; font-size: 10px; }
        .stats-box { border: 1px solid #555; padding: 6px; margin: 8px 0; background: #f5f5f5; }
    </style>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{landscape_style}</head>
    <body>
        {_school_header_html(school_name, ministry_code)}

        <h1>PROCES-VERBAL DU CONSEIL DE CLASSE &mdash; Trimestre {trimester}</h1>

        <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
            <div>
                <div class="info-row"><strong>Classe :</strong> {class_name}</div>
                <div class="info-row"><strong>Annee scolaire :</strong> {academic_year}</div>
                <div class="info-row"><strong>Effectif :</strong> {total_students}</div>
            </div>
            <div>
                <div class="info-row"><strong>Professeur principal :</strong> {main_teacher}</div>
                <div class="info-row"><strong>Chef d'etablissement :</strong> {director}</div>
                <div class="info-row"><strong>DREN :</strong> {dren}</div>
                <div class="info-row"><strong>Date :</strong> {gen_date}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th class="text-center" style="width:30px;">N°</th>
                    <th>Nom et Prenoms</th>
                    <th class="text-center" style="width:60px;">Moyenne</th>
                    <th class="text-center" style="width:40px;">Rang</th>
                    <th class="text-center" style="width:50px;">Absences</th>
                    <th class="text-center" style="width:80px;">Decision auto</th>
                    <th class="text-center" style="width:80px;">Decision finale</th>
                    <th style="width:150px;">Motif modification</th>
                </tr>
            </thead>
            <tbody>
                {decision_rows}
            </tbody>
        </table>

        <div class="stats-box">
            <strong>Recapitulatif :</strong>
            Passages : {passage_count} |
            Repechages : {repechage_count} |
            Redoublements : {redoublement_count} |
            Exclusions : {exclusion_count} |
            Total : {total_students}
        </div>

        {"<div style='margin-top:6px;'><strong>Observations :</strong> " + notes + "</div>" if notes else ""}

        <div style="display: flex; justify-content: space-between; margin-top: 30px;">
            <div style="text-align:center; width:30%;">
                <div>Le Professeur Principal</div>
                <div style="border-top:1px solid #333; margin-top:35px; padding-top:4px;">
                    {main_teacher}
                </div>
            </div>
            <div style="text-align:center; width:30%;">
                <div>Le Chef d'Etablissement</div>
                <div style="border-top:1px solid #333; margin-top:35px; padding-top:4px;">
                    {director}
                </div>
            </div>
            <div style="text-align:center; width:30%;">
                <div>Le DREN</div>
                <div style="border-top:1px solid #333; margin-top:35px; padding-top:4px;">
                    {dren}
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    from weasyprint import HTML  # lazy import — see module docstring

    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Payment Receipt PDF
# ---------------------------------------------------------------------------


def generate_receipt_pdf(payment_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Generate a simple payment receipt PDF.

    payment_data keys:
        payment_id, amount, method, reference, status, notes,
        student_name, fee_description, created_at, received_by_name

    school_settings keys:
        school_name, ministry_code, address, phone
    """
    school_name = school_settings.get("school_name", "Etablissement")
    ministry_code = school_settings.get("ministry_code")
    address = _esc(school_settings.get("address", ""))
    phone = _esc(school_settings.get("phone", ""))

    payment_id = payment_data.get("payment_id", "")
    amount = payment_data.get("amount")
    method = _esc(payment_data.get("method", ""))
    reference = _esc(payment_data.get("reference", ""))
    status = _esc(payment_data.get("status", ""))
    notes = _esc(payment_data.get("notes", ""))
    student_name = _esc(payment_data.get("student_name", ""))
    fee_description = _esc(payment_data.get("fee_description", ""))
    created_at = payment_data.get("created_at")
    received_by = _esc(payment_data.get("received_by_name", ""))

    amount_str = _format_decimal(amount) if isinstance(amount, Decimal) else str(amount or "-")
    pay_date = (
        created_at.strftime("%d/%m/%Y %H:%M")
        if isinstance(created_at, datetime)
        else str(created_at or "")
    )

    method_labels = {
        "cash": "Especes",
        "mobile_money": "Mobile Money",
        "bank_transfer": "Virement bancaire",
        "cheque": "Cheque",
    }
    method_display = method_labels.get(method, method)

    receipt_style = """
    <style>
        @page { size: A5; margin: 12mm; }
        body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 11px; color: #222; }
        h1 { font-size: 14px; text-align: center; margin: 8px 0; border-bottom: 2px solid #333; padding-bottom: 6px; }
        .school-header { text-align: center; margin-bottom: 6px; }
        .school-name { font-size: 13px; font-weight: bold; }
        .ministry-code { font-size: 9px; color: #555; }
        .receipt-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px dotted #ccc; }
        .receipt-label { font-weight: bold; width: 40%; }
        .receipt-value { width: 58%; }
        .amount-box { text-align: center; font-size: 18px; font-weight: bold; margin: 12px 0; padding: 10px; border: 2px solid #333; background: #f5f5f5; }
        .footer-note { text-align: center; font-size: 9px; color: #777; margin-top: 20px; }
    </style>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{receipt_style}</head>
    <body>
        {_school_header_html(school_name, ministry_code)}
        {"<div style='text-align:center; font-size:9px;'>" + address + "</div>" if address else ""}
        {"<div style='text-align:center; font-size:9px;'>Tel : " + phone + "</div>" if phone else ""}

        <h1>RECU DE PAIEMENT</h1>

        <div style="text-align:right; font-size:9px; margin-bottom:8px;">
            N° {payment_id} &mdash; {pay_date}
        </div>

        <div class="amount-box">{amount_str} FCFA</div>

        <div class="receipt-row">
            <span class="receipt-label">Eleve :</span>
            <span class="receipt-value">{student_name}</span>
        </div>
        <div class="receipt-row">
            <span class="receipt-label">Nature du paiement :</span>
            <span class="receipt-value">{fee_description}</span>
        </div>
        <div class="receipt-row">
            <span class="receipt-label">Mode de paiement :</span>
            <span class="receipt-value">{method_display}</span>
        </div>
        {"<div class='receipt-row'><span class='receipt-label'>Reference :</span><span class='receipt-value'>" + reference + "</span></div>" if reference else ""}
        <div class="receipt-row">
            <span class="receipt-label">Statut :</span>
            <span class="receipt-value">{status}</span>
        </div>
        {"<div class='receipt-row'><span class='receipt-label'>Notes :</span><span class='receipt-value'>" + notes + "</span></div>" if notes else ""}

        <div style="display: flex; justify-content: space-between; margin-top: 30px;">
            <div style="text-align:center; width:45%;">
                <div>Le Caissier</div>
                <div style="border-top:1px solid #333; margin-top:35px; padding-top:4px;">
                    {received_by}
                </div>
            </div>
            <div style="text-align:center; width:45%;">
                <div>Le Parent / Tuteur</div>
                <div style="border-top:1px solid #333; margin-top:35px; padding-top:4px;"></div>
            </div>
        </div>

        <div class="footer-note">
            Ce recu fait foi de paiement. A conserver precieusement.
        </div>
    </body>
    </html>
    """

    from weasyprint import HTML  # lazy import — see module docstring

    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# Timetable PDF
# ---------------------------------------------------------------------------

# KLASSCI brand colors
_PRIMARY = "#0F3F8C"
_ACCENT = "#F58220"

# Day order for the grid
_DAYS_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
_DAYS_FR = {
    "monday": "Lundi",
    "tuesday": "Mardi",
    "wednesday": "Mercredi",
    "thursday": "Jeudi",
    "friday": "Vendredi",
    "saturday": "Samedi",
}

# Palette for subjects (cycled)
_SLOT_COLORS = [
    "#E8F0FE",
    "#FEF3E2",
    "#E8F5E9",
    "#FDE8E8",
    "#EDE7F6",
    "#FFF8E1",
    "#E0F7FA",
    "#FCE4EC",
    "#F3E5F5",
    "#E8EAF6",
]


def generate_timetable_pdf(
    slots: list[dict[str, Any]],
    class_name: str,
    academic_year: str,
    school_settings: dict[str, Any],
    day_start: int = 7,
    day_end: int = 18,
) -> bytes:
    """Generate a landscape A4 timetable PDF.

    slots: list of dicts with day, start_time, end_time, subject_name,
           teacher_name, room, subject_color
    """
    school_name = school_settings.get("school_name", "Etablissement")
    ministry_code = school_settings.get("ministry_code")

    # Build hours list
    hours = list(range(day_start, day_end))

    # Assign colors to subjects
    subject_colors: dict[str, str] = {}
    color_idx = 0
    for s in slots:
        sname = s.get("subject_name", "")
        if sname and sname not in subject_colors:
            subject_colors[sname] = (
                s.get("subject_color") or _SLOT_COLORS[color_idx % len(_SLOT_COLORS)]
            )
            color_idx += 1

    # Organize slots by day
    slots_by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in _DAYS_ORDER}
    for s in slots:
        day = s.get("day", "").lower()
        if day in slots_by_day:
            slots_by_day[day].append(s)

    # Sort each day by start_time
    for day in _DAYS_ORDER:
        slots_by_day[day].sort(key=lambda x: x.get("start_time", "00:00"))

    # Build table cells
    def _time_to_float(t: str) -> float:
        parts = t.split(":")
        return int(parts[0]) + int(parts[1]) / 60

    def _cell_for_hour(day_slots: list[dict[str, Any]], hour: int) -> str:
        """Return HTML for a cell at the given hour. Handle multi-hour spans."""
        for s in day_slots:
            start = _time_to_float(s["start_time"])
            end = _time_to_float(s["end_time"])
            if abs(start - hour) < 0.01:
                span = max(1, round(end - start))
                bg = subject_colors.get(s.get("subject_name", ""), "#f0f0f0")
                subject = _esc(s.get("subject_name", ""))
                teacher = _esc(s.get("teacher_name", ""))
                room = _esc(s.get("room", ""))
                time_str = f"{s['start_time']}-{s['end_time']}"
                room_div = f'<div style="color:#888;">{room}</div>' if room else ""
                return (
                    f'<td rowspan="{span}" style="background:{bg}; vertical-align:top; padding:4px; '
                    f'border:1px solid #ccc; font-size:8px; line-height:1.3;">'
                    f'<div style="font-weight:bold; font-size:9px; color:{_PRIMARY};">{subject}</div>'
                    f'<div style="color:#555;">{teacher}</div>'
                    f"{room_div}"
                    f'<div style="color:#999; font-size:7px;">{time_str}</div>'
                    f"</td>"
                )
            elif start < hour < end:
                return ""
        return '<td style="border:1px solid #eee;"></td>'

    # Build rows
    table_rows = ""
    for hour in hours:
        cells = ""
        for day in _DAYS_ORDER:
            cell = _cell_for_hour(slots_by_day[day], hour)
            cells += cell
        table_rows += f"""
        <tr>
            <td style="background:#f8f9fa; font-weight:bold; text-align:center; font-size:9px;
                        border:1px solid #ddd; width:50px; color:{_PRIMARY};">
                {hour:02d}:00
            </td>
            {cells}
        </tr>
        """

    # Day headers
    day_headers = "".join(
        f'<th style="background:{_PRIMARY}; color:white; text-align:center; padding:6px; '
        f'font-size:10px; border:1px solid {_PRIMARY};">{_DAYS_FR.get(d, d)}</th>'
        for d in _DAYS_ORDER
    )

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    timetable_style = f"""
    <style>
        @page {{ size: A4 landscape; margin: 10mm; }}
        body {{ font-family: 'Helvetica', 'Arial', sans-serif; font-size: 10px; color: #222; margin: 0; }}
        .header {{ text-align: center; margin-bottom: 8px; }}
        .school-name {{ font-size: 14px; font-weight: bold; color: {_PRIMARY}; }}
        .class-info {{ font-size: 12px; color: {_ACCENT}; font-weight: bold; margin: 4px 0; }}
        .sub-info {{ font-size: 9px; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .footer {{ text-align: center; font-size: 8px; color: #999; margin-top: 8px; }}
    </style>
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{timetable_style}</head>
    <body>
        <div class="header">
            {_school_header_html(school_name, ministry_code)}
            <div class="class-info">EMPLOI DU TEMPS &mdash; {_esc(class_name)}</div>
            <div class="sub-info">Annee scolaire : {_esc(academic_year)}</div>
        </div>

        <table>
            <thead>
                <tr>
                    <th style="background:{_PRIMARY}; color:white; text-align:center; padding:6px;
                                font-size:10px; border:1px solid {_PRIMARY}; width:50px;">Heure</th>
                    {day_headers}
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>

        <div class="footer">
            Imprime le {now_str} &mdash; KLASSCI College
        </div>
    </body>
    </html>
    """

    from weasyprint import HTML  # lazy import — see module docstring

    return HTML(string=html).write_pdf()
