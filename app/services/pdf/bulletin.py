"""Bulletin de notes — PDF par élève et par trimestre.

Document académique :
- En-tête établissement + bandeau République CI
- Identité élève + classe + année scolaire
- Tableau des matières (moyenne, coefficient)
- KPIs synthèse : moyenne générale, rang, mention
- Décision du conseil + appréciation prof principal (optionnels)
- Signatures Prof principal / Parent / Chef d'Établissement

Refactor 2026-05-18 : utilise `components.py` + `PDFTheme.from_school`.
"""

from __future__ import annotations

from typing import Any

from app.services.pdf import components as ui
from app.services.pdf._helpers import esc, format_decimal, image_to_datauri
from app.services.pdf.theme import PDFTheme

_DECISION_LABELS = {
    "passage": "Admis en classe supérieure",
    "repechage": "Repêché par le conseil",
    "redoublement": "Redouble la classe",
    "exclusion": "Exclu de l'établissement",
}

_GENRE_LABELS = {"M": "Masculin", "F": "Féminin"}


def _initials(nom: str) -> str:
    """Les initiales, quand aucune photo n'a ete deposee.

    Un cadre vide marque « PHOTO » se lit comme un dossier incomplet. Deux
    lettres se lisent comme un choix.
    """
    morceaux = [m for m in nom.replace("-", " ").split() if m]
    if not morceaux:
        return "?"
    if len(morceaux) == 1:
        return morceaux[0][:2].upper()
    return (morceaux[0][0] + morceaux[-1][0]).upper()


def _photo_cell(nom: str, photo_url: str | None, *, theme: PDFTheme) -> str:
    """La photo de l'eleve, ou ses initiales.

    Le bulletin ivoirien reserve ce cadre a la photo : c'est ce qui rend le
    document opposable au guichet quand un eleve vient chercher le sien. Une
    URL qui ne se resout pas ne doit pas laisser un trou, d'ou le repli.
    """
    if photo_url:
        data = image_to_datauri(photo_url)
        if data:
            return f'<img class="bul-photo" src="{data}" alt="" />'
    return f'<div class="bul-photo bul-photo-initiales">{esc(_initials(nom))}</div>'


def _identity_card(d: dict[str, Any], *, theme: PDFTheme) -> str:
    """Identite de l'eleve et sa photo, comme sur le bulletin officiel."""
    naissance = d.get("birth_date")
    ne_le = naissance.strftime("%d/%m/%Y") if hasattr(naissance, "strftime") else ""
    lieu = d.get("birth_place") or ""
    if ne_le and lieu:
        naissance_txt = f"{ne_le} à {lieu}"
    else:
        naissance_txt = ne_le or lieu or "—"

    genre = _GENRE_LABELS.get(str(d.get("genre") or ""), "—")
    rang = d.get("rank")
    effectif = d.get("total_students") or 0
    numero = f"{rang}/{effectif}" if rang and effectif else "—"

    lignes = [
        ("Matricule", d.get("matricule") or "—"),
        ("Né(e) le", naissance_txt),
        ("Genre", genre),
        ("Classe", d.get("class_name") or "—"),
        ("Bulletin N°", numero),
    ]
    # Deux colonnes de paires : lisible sur une demi-largeur, et chaque paire
    # reste solidaire au retour a la ligne.
    milieu = (len(lignes) + 1) // 2
    colonnes = (lignes[:milieu], lignes[milieu:])
    corps = ""
    for col in colonnes:
        cases = "".join(
            f'<tr><td class="bul-id-label">{esc(lab)}</td>'
            f'<td class="bul-id-valeur">{esc(str(val))}</td></tr>'
            for lab, val in col
        )
        corps += f'<td class="bul-id-col"><table class="bul-id-sub">{cases}</table></td>'

    photo = _photo_cell(d.get("student_name") or "", d.get("photo_url"), theme=theme)
    return (
        '<table class="bul-identite"><tr>'
        '<td class="bul-id-corps">'
        f'<div class="bul-id-nom">{esc(d.get("student_name") or "")}</div>'
        f'<table class="bul-id-grille"><tr>{corps}</tr></table>'
        "</td>"
        f'<td class="bul-id-photo">{photo}</td>'
        "</tr></table>"
    )


def _identity_styles() -> str:
    return """
    <style>
      .bul-identite {
        width: 100%; border-collapse: collapse;
        border: 1px solid var(--border); border-radius: 6px;
        margin: 10px 0;
      }
      .bul-identite > tr > td { padding: 9px 11px; vertical-align: middle; }
      .bul-id-corps { width: auto; }
      .bul-id-nom {
        font-size: 13px; font-weight: 700; color: var(--primary);
        text-transform: uppercase; letter-spacing: 0.2px; margin-bottom: 5px;
      }
      .bul-id-grille { width: 100%; border-collapse: collapse; font-size: 9.5px; }
      .bul-id-col { vertical-align: top; padding-right: 16px; }
      .bul-id-sub { border-collapse: collapse; }
      .bul-id-sub td { padding: 1px 0 1px 0; }
      .bul-id-label { color: var(--muted); padding-right: 10px !important; white-space: nowrap; }
      .bul-id-valeur { font-weight: 600; color: var(--ink); white-space: nowrap; }
      .bul-id-photo { width: 78px; text-align: right; }
      .bul-photo {
        width: 68px; height: 85px; object-fit: cover;
        border: 1px solid var(--border); border-radius: 4px;
      }
      .bul-photo-initiales {
        display: flex; align-items: center; justify-content: center;
        background: var(--soft-bg); color: var(--primary);
        font-size: 26px; font-weight: 700; letter-spacing: 1px;
      }
    </style>
    """


def _subject_rows(subject_averages: list[dict[str, Any]]) -> list[list[Any]]:
    """Rows : Matière (+prof) / Moy. / Coef / Rang / Moy. classe / Appréciation."""
    rows: list[list[Any]] = []
    for sa in subject_averages:
        name_cell = f"<strong>{ui.esc(sa.get('subject_name', ''))}</strong>"
        teacher = sa.get("teacher_name")
        if teacher:
            name_cell += (
                f"<br/><span style='font-size:8px;color:var(--muted);'>{ui.esc(teacher)}</span>"
            )
        raw_avg = sa.get("average")
        coef = sa.get("coefficient", 1) or 1
        rank = sa.get("rank")
        class_avg = sa.get("class_avg")
        try:
            points = float(raw_avg) * float(coef) if raw_avg is not None else None
        except (TypeError, ValueError):
            points = None
        rows.append(
            [
                {"value": name_cell, "type": "html"},
                {"value": format_decimal(raw_avg), "type": "num"},
                {"value": str(coef), "type": "num"},
                # Moyenne x coefficient : c'est cette colonne que le conseil de
                # classe additionne pour retrouver la moyenne generale. Sans
                # elle, le parent ne peut pas refaire le calcul.
                {"value": format_decimal(points) if points is not None else "—", "type": "num"},
                {"value": str(rank) if rank else "—", "type": "num"},
                {
                    "value": format_decimal(class_avg) if class_avg is not None else "—",
                    "type": "muted",
                },
                {"value": ui.appreciation_label(raw_avg), "type": "muted"},
            ]
        )
    return rows


def _total_row(subject_averages: list[dict[str, Any]]) -> list[Any] | None:
    """La ligne « Total » : somme des coefficients et somme des points.

    Presente sur le bulletin officiel, et c'est elle qui rend la moyenne
    generale verifiable a la main.
    """
    coef_total = 0.0
    points_total = 0.0
    vu = False
    for sa in subject_averages:
        try:
            coef = float(sa.get("coefficient", 1) or 1)
            moy = sa.get("average")
            coef_total += coef
            if moy is not None:
                points_total += float(moy) * coef
                vu = True
        except (TypeError, ValueError):
            continue
    if not vu:
        return None
    return [
        {"value": "Total", "type": "emphasis"},
        {"value": "", "type": "num"},
        {"value": format_decimal(coef_total), "type": "emphasis"},
        {"value": format_decimal(points_total), "type": "emphasis"},
        {"value": "", "type": "num"},
        {"value": "", "type": "muted"},
        {"value": "", "type": "muted"},
    ]


def _keyfigures_band(average: str, rank: Any, total_students: Any, mention: str) -> str:
    """Bande compacte 3 chiffres-clés : Moyenne / Rang / Mention (focale accent)."""
    avg_display = (
        f'{average}<span style="font-size:11px">/20</span>' if average not in ("-", "") else "—"
    )
    if rank:
        rank_display = f'{rank}<span style="font-size:11px">/{total_students}</span>'
    else:
        rank_display = "—"
    mention_display = ui.mention_label(mention) if mention else "—"
    return (
        '<div class="pdf-keyfigures">'
        '<div class="pdf-keyfigure">'
        '<div class="pdf-keyfigure-label">Moyenne générale</div>'
        f'<div class="pdf-keyfigure-value">{avg_display}</div></div>'
        '<div class="pdf-keyfigure">'
        '<div class="pdf-keyfigure-label">Rang</div>'
        f'<div class="pdf-keyfigure-value">{rank_display}</div></div>'
        '<div class="pdf-keyfigure">'
        '<div class="pdf-keyfigure-label">Mention</div>'
        f'<div class="pdf-keyfigure-value is-focal">{ui.esc(mention_display)}</div></div>'
        "</div>"
    )


def _synthesis_block(
    class_stats: dict[str, Any], absences: dict[str, Any], *, theme: PDFTheme
) -> str:
    """Bandeau synthèse : moyenne de classe, écart, absences, retards."""
    class_avg = class_stats.get("class_avg")
    class_min = class_stats.get("class_min")
    class_max = class_stats.get("class_max")
    parts: list[str] = []
    if class_avg is not None:
        parts.append(f"<strong>Moyenne de la classe :</strong> {format_decimal(class_avg)} / 20")
    if class_min is not None and class_max is not None:
        parts.append(
            f"<strong>Écart de la classe :</strong> "
            f"{format_decimal(class_min)} – {format_decimal(class_max)}"
        )
    parts.append(f"<strong>Absences :</strong> {int(absences.get('absent', 0) or 0)}")
    late = int(absences.get("late", 0) or 0)
    if late:
        parts.append(f"<strong>Retards :</strong> {late}")
    inner = " &nbsp;·&nbsp; ".join(parts)
    return (
        f'<div style="margin:10px 0; padding:8px 12px; border:1px solid var(--border); '
        f'border-radius:6px; background:var(--soft-bg); font-size:10px; color:var(--ink);">'
        f"{inner}</div>"
    )


def generate_bulletin_pdf(bulletin_data: dict[str, Any], school_settings: dict[str, Any]) -> bytes:
    """Generate a PDF bulletin for a single student.

    bulletin_data keys:
        student_name, class_name, trimester, academic_year_name,
        average, rank, total_students, mention, council_decision,
        teacher_comment, subject_averages (list of dicts with
        subject_name, average, coefficient), generated_at
    """
    from weasyprint import HTML  # lazy import

    theme = PDFTheme.from_school(school_settings)
    school_name = school_settings.get("school_name") or ""

    class_name = bulletin_data.get("class_name", "")
    trimester = bulletin_data.get("trimester", "")
    academic_year = bulletin_data.get("academic_year_name", "")
    average = format_decimal(bulletin_data.get("average"))
    rank = bulletin_data.get("rank")
    total_students = bulletin_data.get("total_students", 0)
    mention = bulletin_data.get("mention", "")
    council_decision = bulletin_data.get("council_decision", "")
    teacher_comment = bulletin_data.get("teacher_comment", "")
    subject_averages = bulletin_data.get("subject_averages", []) or []
    reference = bulletin_data.get("reference")
    verification = bulletin_data.get("verification") or {}
    class_stats = bulletin_data.get("class_stats") or {}
    absences = bulletin_data.get("absences") or {}

    _table_rows = _subject_rows(subject_averages)
    _total = _total_row(subject_averages)
    if _total:
        _table_rows = [*_table_rows, _total]

    table_section = ui.premium_table(
        headers=[
            "Matière",
            {"label": "Moy. / 20", "align": "right"},
            {"label": "Coef.", "align": "right"},
            {"label": "M. Coef.", "align": "right"},
            {"label": "Rang", "align": "right"},
            {"label": "Moy. classe", "align": "right"},
            "Appréciation",
        ],
        rows=_table_rows,
        theme=theme,
        empty_message="Aucune note saisie pour ce trimestre.",
        col_widths=["28%", "10%", "8%", "10%", "8%", "13%", "23%"],
    )

    keyfigures = _keyfigures_band(average, rank, total_students, mention)

    synthesis = _synthesis_block(class_stats, absences, theme=theme)

    decision_block = ""
    if council_decision:
        decision_block = (
            f'<div style="margin:12px 0; padding:8px 12px; '
            f'border-left:3px solid var(--primary); background:var(--soft-bg); font-size:11px;">'
            f"<strong>Décision du conseil :</strong> "
            f"{ui.esc(_DECISION_LABELS.get(str(council_decision), str(council_decision)))}"
            f"</div>"
        )

    comment_block = ""
    if teacher_comment:
        comment_block = (
            ui.section_title("Appréciation du professeur principal", theme=theme)
            + f'<div style="padding:8px 12px; border:1px solid var(--border); '
            f"border-radius:6px; background:var(--soft-bg); font-size:11px; "
            f'line-height:1.5;">{ui.esc(teacher_comment)}</div>'
        )

    signatures = ui.signature_block(
        roles=[
            {"role": "Le Professeur Principal"},
            {"role": "Le Parent / Tuteur"},
            {"role": "Le Chef d'Établissement"},
        ],
        theme=theme,
    )

    html = f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8">{ui.base_styles(theme, page_size="A4", margin="15mm")}</head>
    <body>
        {ui.page_decoration(theme=theme, watermark_text=school_name)}
        <div class="pdf-page-body">
        {
        ui.premium_header(
            school_settings,
            theme=theme,
            doc_type=f"BULLETIN — TRIMESTRE {trimester}",
            doc_subtitle=f"{class_name} — {academic_year}" if class_name else None,
        )
    }

        {_identity_styles()}

        {_identity_card(bulletin_data, theme=theme)}

        {keyfigures}

        {table_section}

        {synthesis}

        {decision_block}

        {comment_block}

        {signatures}

        {
        ui.premium_footer(
            school_settings,
            theme=theme,
            reference=reference,
            note="Document officiel — à conserver précieusement.",
            cev_svg=verification.get("cev_svg"),
            seal_code=verification.get("seal_code"),
            verify_url=verification.get("verify_url"),
            manual_verify_url=verification.get("manual_verify_url"),
        )
    }
        </div>
    </body>
    </html>
    """

    return HTML(string=html).write_pdf()
