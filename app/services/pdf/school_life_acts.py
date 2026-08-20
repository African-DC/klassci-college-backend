"""Les quatre actes de vie scolaire du collège, sur une coquille commune.

Demande de dossier scolaire, billet d'entrée, convocation de parent et billet
d'annulation de zéro. Ils partagent l'en-tête officiel à trois colonnes et la
même mise en page de corps, parce qu'ils sortent du même bureau et se
présentent au même guichet.

Trois portent le sceau numérique : ils quittent l'établissement ou modifient
une note. Le billet d'entrée n'en porte pas — il est imprimé par dizaines
chaque matin, une référence en pied suffit à le retrouver.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._official_header import (
    blank,
    filled,
    official_act_styles,
    official_tri_masthead,
    signature_zone,
)
from app.services.pdf.theme import PDFTheme


def _fr_date(value: date | datetime | None, *, width_mm: int = 26) -> str:
    """Date au format jj/mm/aaaa, ou un blanc à remplir si elle est inconnue."""
    if value is None:
        return blank(width_mm)
    return f'<span class="acte-filled">{value.strftime("%d/%m/%Y")}</span>'


def _agreed(genre: str | None, masculine: str, feminine: str) -> str:
    """Accorde un participe au genre de l'élève, sans parenthèses quand on sait."""
    if genre == "F":
        return feminine
    if genre == "M":
        return masculine
    return f"{masculine}(e)"


def _student_name(student: dict[str, Any]) -> str:
    return f"{student.get('first_name') or ''} {student.get('last_name') or ''}".strip()


def _render_act(
    *,
    school: dict[str, Any],
    theme: PDFTheme,
    academic_year_name: str | None,
    title: str,
    body_html: str,
    signatory_role: str,
    issued_at: datetime,
    reference: str | None,
    footer_note: str,
    verification: dict[str, Any] | None = None,
) -> bytes:
    """Assemble et rend un acte. Seuls le titre, le corps et le signataire varient."""
    from weasyprint import HTML  # import tardif : WeasyPrint charge GTK au premier appel

    verification = verification or {}

    header_html = official_tri_masthead(
        school,
        theme=theme,
        academic_year_name=academic_year_name,
        doc_title=title,
    )
    bottom_html = f"""
        <div class="acte-place-date">Fait le {issued_at.strftime("%d/%m/%Y")}</div>
        {signature_zone(signatory_role)}
        {
        ui.premium_footer(
            school,
            theme=theme,
            reference=reference,
            note=footer_note,
            cev_svg=verification.get("cev_svg"),
            seal_code=verification.get("seal_code"),
            verify_url=verification.get("verify_url"),
            manual_verify_url=verification.get("manual_verify_url"),
        )
    }
    """

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">
        {ui.base_styles(theme, page_size="A4", margin="14mm")}
        {official_act_styles(theme)}
    </head>
    <body>
        {
        ui.document_frame(
            theme=theme,
            header_html=header_html,
            body_html=f'<div class="acte-body">{body_html}</div>',
            bottom_html=bottom_html,
        )
    }
    </body>
    </html>
    """
    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# 1. Demande de dossier scolaire
# ---------------------------------------------------------------------------


def generate_school_file_request_pdf(
    data: dict[str, Any], school_settings: dict[str, Any]
) -> bytes:
    """Courrier réclamant le dossier d'un élève à son établissement d'origine."""
    theme = PDFTheme.from_school(school_settings)
    student = data.get("student", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    year_label = data.get("academic_year_name") or ""
    enrolled = _agreed(student.get("genre"), "inscrit", "inscrite")

    decision_html = ""
    if student.get("transfer_decision_number"):
        decision_html = (
            "<p>Décision de transfert n° "
            f"{filled(student['transfer_decision_number'], width_mm=45)}.</p>"
        )

    body_html = f"""
        <p>Monsieur le Chef d'Établissement de
        {filled(student.get("previous_school"), width_mm=70)},</p>
        <p>Je vous serais reconnaissant de bien vouloir nous faire parvenir dans
        les meilleurs délais l'ensemble du dossier de l'élève
        {filled(_student_name(student), width_mm=70)},
        {enrolled} en classe de {filled(data.get("class_name"), width_mm=35)},
        matricule {filled(student.get("enrollment_number"), width_mm=40)},
        durant l'année scolaire {filled(year_label, width_mm=35)}.</p>
        {decision_html}
        <p>Dans l'attente de votre diligence, je vous prie d'agréer, Monsieur le
        Chef d'Établissement, l'expression de ma considération distinguée.</p>
    """

    return _render_act(
        school=school_settings,
        theme=theme,
        academic_year_name=year_label,
        title="Demande de dossier scolaire",
        body_html=body_html,
        signatory_role="Le Directeur des Études",
        issued_at=issued_at,
        reference=data.get("reference"),
        footer_note="Document officiel — toute falsification est passible de poursuites.",
        verification=data.get("verification"),
    )


# ---------------------------------------------------------------------------
# 2. Billet d'entrée
# ---------------------------------------------------------------------------


def generate_entry_slip_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Billet qui réadmet un élève en cours après une absence régularisée."""
    theme = PDFTheme.from_school(school_settings)
    student = data.get("student", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    authorized = _agreed(student.get("genre"), "autorisé", "autorisée")

    absence_html = ""
    if data.get("absence_date"):
        absence_html = (
            f"<p>Absence du {_fr_date(data['absence_date'])} régularisée par le bureau "
            "de la vie scolaire.</p>"
        )

    body_html = f"""
        <p>L'élève {filled(_student_name(student), width_mm=70)},
        classe {filled(data.get("class_name"), width_mm=35)},
        matricule {filled(student.get("enrollment_number"), width_mm=40)},
        est {authorized} à débuter les cours le {_fr_date(data.get("resume_date"))}.</p>
        {absence_html}
    """

    return _render_act(
        school=school_settings,
        theme=theme,
        academic_year_name=data.get("academic_year_name"),
        title="Billet d'entrée",
        body_html=body_html,
        signatory_role="L'Éducateur",
        issued_at=issued_at,
        reference=data.get("reference"),
        footer_note="Pièce interne — à présenter à l'enseignant pour être admis en cours.",
    )


# ---------------------------------------------------------------------------
# 3. Convocation de parent
# ---------------------------------------------------------------------------


def generate_parent_summons_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Convocation du tuteur légal d'un élève, avec motif et créneau."""
    theme = PDFTheme.from_school(school_settings)
    student = data.get("student", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    summons_time = data.get("summons_time")
    time_html = (
        f'<span class="acte-filled">{summons_time.strftime("%H h %M")}</span>'
        if summons_time is not None
        else blank(20)
    )

    body_html = f"""
        <p>M./Mme/Mlle {filled(data.get("parent_name"), width_mm=70)},
        tuteur légal de l'élève {filled(_student_name(student), width_mm=65)},
        matricule {filled(student.get("enrollment_number"), width_mm=40)},
        en classe de {filled(data.get("class_name"), width_mm=35)},
        êtes convoqué(e) par l'administration du collège
        le {_fr_date(data.get("summons_date"))} à {time_html}.</p>
        <p>Motif : {filled(data.get("reason"), width_mm=95)}.</p>
        <p>Votre présence est indispensable. Merci de vous présenter au bureau de
        la vie scolaire muni(e) de la présente convocation.</p>
    """

    return _render_act(
        school=school_settings,
        theme=theme,
        academic_year_name=data.get("academic_year_name"),
        title="Convocation de parent",
        body_html=body_html,
        signatory_role="L'Éducateur",
        issued_at=issued_at,
        reference=data.get("reference"),
        footer_note="Document officiel — toute falsification est passible de poursuites.",
        verification=data.get("verification"),
    )


# ---------------------------------------------------------------------------
# 4. Billet d'annulation de zéro
# ---------------------------------------------------------------------------


def _evaluations_table(rows: list[dict[str, Any]], *, theme: PDFTheme) -> str:
    """Les évaluations rouvertes, nommées une à une.

    Sans cette liste, « les évaluations manquées » resterait une formule ; le
    professeur qui reçoit l'élève doit savoir exactement quoi lui faire repasser.
    """
    if not rows:
        return ""
    table_rows = [
        [
            row.get("subject_name") or "—",
            row.get("title") or "—",
            row["date"].strftime("%d/%m/%Y") if row.get("date") else "—",
            {"value": str(row.get("coefficient") or 1), "type": "num"},
        ]
        for row in rows
    ]
    return ui.premium_table(
        ["Matière", "Évaluation", "Date", {"label": "Coef.", "align": "right"}],
        table_rows,
        theme=theme,
        col_widths=["30%", "40%", "18%", "12%"],
    )


def generate_zero_cancellation_pdf(data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Billet rouvrant les évaluations qu'un élève a manquées."""
    theme = PDFTheme.from_school(school_settings)
    student = data.get("student", {}) or {}
    issued_at = data.get("issued_at") or datetime.utcnow()
    authorized = _agreed(student.get("genre"), "autorisé", "autorisée")

    body_html = f"""
        <p>L'élève {filled(_student_name(student), width_mm=70)},
        matricule {filled(student.get("enrollment_number"), width_mm=40)},
        en classe de {filled(data.get("class_name"), width_mm=35)},
        est {authorized} à reprendre les évaluations manquées
        du {_fr_date(data.get("period_start"))} au {_fr_date(data.get("period_end"))}.</p>
        <p>MOTIF : {filled(data.get("reason"), width_mm=95)}.</p>
    """
    table_html = _evaluations_table(data.get("evaluations") or [], theme=theme)
    if table_html:
        body_html += (
            '<div style="line-height:1.45; margin-top:4px;">'
            f"{ui.section_title('Évaluations concernées', theme=theme)}{table_html}</div>"
        )
    body_html += (
        '<p style="font-size:10px; line-height:1.6; margin-top:14px;">Le présent billet '
        "rouvre les évaluations ci-dessus. La note de rattrapage est saisie par "
        "l'enseignant de la matière, comme toute autre note.</p>"
    )

    return _render_act(
        school=school_settings,
        theme=theme,
        academic_year_name=data.get("academic_year_name"),
        title="Billet d'annulation de zéro",
        body_html=body_html,
        signatory_role="L'Éducateur",
        issued_at=issued_at,
        reference=data.get("reference"),
        footer_note="Document officiel — toute falsification est passible de poursuites.",
        verification=data.get("verification"),
    )
