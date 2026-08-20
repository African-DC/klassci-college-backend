"""En-tête administratif à trois colonnes et coquille des actes de vie scolaire.

Fonction sœur de `_chrome.premium_header`, pas une réécriture : elle réutilise
`_eyebrow_html`, `image_to_datauri` et le filet `.doc-filet`. La différence est
la mise en page attendue par l'administration ivoirienne — ministère et
identité de l'établissement à gauche, logo et devise au centre, République et
armoiries à droite — que le masthead à deux colonnes ne peut pas rendre.

Les actes de vie scolaire (demande de dossier, billet d'entrée, convocation,
annulation de zéro) tiennent tous sur cette même coquille : c'est ce qui fait
qu'ils se ressemblent en main et se reconnaissent au premier coup d'œil.
"""

from __future__ import annotations

from typing import Any

from app.services.pdf._chrome import _eyebrow_html
from app.services.pdf._helpers import esc, image_to_datauri
from app.services.pdf.theme import PDFTheme

_MINISTRY_LINE = "MINISTÈRE DE L'ÉDUCATION NATIONALE ET DE L'ALPHABÉTISATION"
_REPUBLIC_LINE = "RÉPUBLIQUE DE CÔTE D'IVOIRE"
_REPUBLIC_DEVISE = "UNION - DISCIPLINE - TRAVAIL"

# Emblème de repli quand l'établissement n'a pas encore déposé le fichier
# officiel des armoiries. Volontairement stylisé et sobre : imprimer une
# reproduction approximative des armoiries de la République serait pire qu'un
# symbole assumé comme tel.
_FALLBACK_EMBLEM_SVG = """
<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" class="acte-emblem-svg">
  <circle cx="32" cy="32" r="30" fill="none" stroke="currentColor" stroke-width="1.4"/>
  <ellipse cx="32" cy="29" rx="10" ry="13" fill="currentColor"/>
  <ellipse cx="17" cy="26" rx="9" ry="12" fill="currentColor"/>
  <ellipse cx="47" cy="26" rx="9" ry="12" fill="currentColor"/>
  <path d="M32 39 q -3 9 0 14 q 2 3 5 1" fill="none" stroke="currentColor"
        stroke-width="3.2" stroke-linecap="round"/>
  <path d="M25 40 q -3 6 -6 8" fill="none" stroke="currentColor"
        stroke-width="1.6" stroke-linecap="round"/>
  <path d="M39 40 q 3 6 6 8" fill="none" stroke="currentColor"
        stroke-width="1.6" stroke-linecap="round"/>
</svg>
"""


def official_act_styles(theme: PDFTheme) -> str:
    """CSS propre aux actes : en-tête trois colonnes, corps aéré, blancs à remplir."""
    _ = theme  # les couleurs viennent des variables posées par `base_styles`
    return """
    <style>
        .acte-masthead {
            display: flex; align-items: flex-start; gap: 12px;
            padding-bottom: 8px;
        }
        .acte-col { font-size: 8.5px; line-height: 1.55; color: var(--ink); }
        .acte-col-left { flex: 1 1 37%; }
        .acte-col-center { flex: 0 0 24%; text-align: center; }
        .acte-col-right { flex: 1 1 33%; text-align: center; }
        .acte-authority {
            font-weight: 700; text-transform: uppercase; letter-spacing: 0.2px;
            font-size: 8px; line-height: 1.4;
        }
        .acte-school-name {
            font-family: var(--font-display); font-weight: 700;
            font-size: 11.5px; color: var(--primary);
            text-transform: uppercase; line-height: 1.25; margin-top: 3px;
        }
        .acte-meta { margin-top: 2px; color: var(--muted); font-size: 8px; }
        .acte-logo img { max-height: 58px; max-width: 118px; object-fit: contain; }
        .acte-center-motto {
            font-size: 8px; color: var(--muted); font-style: italic;
            margin-top: 4px; line-height: 1.35;
        }
        .acte-emblem { color: var(--primary); margin: 4px auto 3px; }
        .acte-emblem img { max-height: 46px; max-width: 46px; object-fit: contain; }
        .acte-emblem-svg { width: 46px; height: 46px; display: block; margin: 0 auto; }
        .acte-year {
            font-weight: 700; font-size: 8.5px; text-transform: uppercase;
            letter-spacing: 0.3px; margin-top: 3px;
        }
        .acte-secondary-motto {
            text-align: center; font-style: italic; font-size: 9.5px;
            color: var(--ink); margin: 6px 0 8px;
        }
        .acte-title {
            text-align: center; font-family: var(--font-display); font-weight: 700;
            font-size: 17px; letter-spacing: 1.4px; color: var(--ink);
            text-transform: uppercase; margin: 20px 0 6px;
            text-decoration: underline; text-underline-offset: 5px;
        }
        .acte-body {
            font-size: 12px; line-height: 2.35; text-align: justify;
            margin: 20px 4mm 0;
        }
        .acte-body p { margin: 0 0 14px; }
        /* Blanc à remplir à la main : pointillés, jamais un trait plein qui se
           confondrait avec un soulignement. */
        .acte-blank {
            display: inline-block; border-bottom: 0.9px dotted var(--ink);
            vertical-align: baseline;
        }
        .acte-filled { font-weight: 600; }
        .acte-place-date {
            text-align: right; font-style: italic; font-size: 11px;
            color: var(--muted); margin-top: 22px;
        }
        .acte-signature { text-align: right; margin-top: 6px; }
        .acte-signature-role {
            font-weight: 700; font-size: 10px; text-transform: uppercase;
            letter-spacing: 0.4px; color: var(--ink);
        }
        .acte-signature-space {
            height: 46px; border-bottom: 0.75px solid var(--ink);
            width: 210px; margin-left: auto;
        }
        .acte-signature-name {
            font-size: 9px; color: var(--muted); margin-top: 4px;
        }
        .acte-note {
            font-size: 8.5px; color: var(--muted); margin-top: 16px;
            padding-top: 6px; border-top: 0.75px solid var(--border);
        }
    </style>
    """


def _emblem_html(school: dict[str, Any]) -> str:
    """Armoiries déposées par l'établissement, ou emblème de repli."""
    data = image_to_datauri(school.get("coat_of_arms_url"))
    if data:
        return f'<div class="acte-emblem"><img src="{data}" alt="Armoiries" /></div>'
    return f'<div class="acte-emblem">{_FALLBACK_EMBLEM_SVG}</div>'


def _logo_html(school: dict[str, Any]) -> str:
    """Logo de l'établissement, ou monogramme construit sur son nom."""
    data = image_to_datauri(school.get("logo_url"))
    if data:
        return f'<div class="acte-logo"><img src="{data}" alt="Logo" /></div>'
    words = [w for w in (school.get("school_name") or "E").split() if w]
    initials = "".join(w[0] for w in words[:2]).upper() or "E"
    return (
        '<div class="acte-logo" style="display:flex; justify-content:center;">'
        f'<div class="pdf-monogram">{esc(initials)}</div>'
        "</div>"
    )


def official_tri_masthead(
    school: dict[str, Any],
    *,
    theme: PDFTheme,
    academic_year_name: str | None = None,
    doc_title: str | None = None,
    show_ci_banner: bool = False,
) -> str:
    """En-tête officiel : trois colonnes, devise secondaire, filet, titre.

    `show_ci_banner` reste disponible mais par défaut désactivé : la mention de
    la République et celle du ministère figurent déjà dans les colonnes, et
    l'eyebrow de `premium_header` les répéterait une troisième fois en haut de
    page.
    """
    _ = theme
    school = school or {}

    left_lines: list[str] = [f'<div class="acte-authority">{esc(_MINISTRY_LINE)}</div>']
    if school.get("drena_name"):
        left_lines.append(f'<div class="acte-authority">DRENA {esc(school["drena_name"])}</div>')
    left_lines.append(
        f'<div class="acte-school-name">{esc(school.get("school_name") or "Établissement")}</div>'
    )
    meta: list[str] = []
    if school.get("ministry_code"):
        meta.append(f"CODE DE L'ÉTABLISSEMENT : {esc(school['ministry_code'])}")
    if school.get("address"):
        meta.append(esc(school["address"]))
    if school.get("phone"):
        meta.append(f"Tél : {esc(school['phone'])}")
    if meta:
        left_lines.append(f'<div class="acte-meta">{"<br/>".join(meta)}</div>')

    motto_html = (
        f'<div class="acte-center-motto">{esc(school["motto"])}</div>'
        if school.get("motto")
        else ""
    )
    year_html = (
        f'<div class="acte-year">ANNÉE SCOLAIRE {esc(academic_year_name)}</div>'
        if academic_year_name
        else ""
    )
    secondary_motto = (
        f'<div class="acte-secondary-motto">{esc(school["secondary_motto"])}</div>'
        if school.get("secondary_motto")
        else ""
    )
    title_html = f'<div class="acte-title">{esc(doc_title)}</div>' if doc_title else ""

    return f"""
    {_eyebrow_html() if show_ci_banner else ""}
    <div class="acte-masthead">
        <div class="acte-col acte-col-left">{"".join(left_lines)}</div>
        <div class="acte-col acte-col-center">
            {_logo_html(school)}
            {motto_html}
        </div>
        <div class="acte-col acte-col-right">
            <div class="acte-authority">{esc(_REPUBLIC_LINE)}</div>
            <div class="acte-authority">{esc(_REPUBLIC_DEVISE)}</div>
            {_emblem_html(school)}
            {year_html}
        </div>
    </div>
    {secondary_motto}
    <div class="doc-filet"></div>
    {title_html}
    """


def blank(width_mm: int = 40) -> str:
    """Un blanc à remplir au stylo, de largeur explicite."""
    return f'<span class="acte-blank" style="width:{width_mm}mm">&nbsp;</span>'


def filled(value: str | None, *, width_mm: int = 40) -> str:
    """La valeur si le logiciel la connaît, sinon un blanc de la même largeur.

    Un acte administratif se remplit partiellement à la main : imprimer un
    « None » ou une chaîne vide obligerait l'éducateur à raturer.
    """
    text = (value or "").strip()
    if not text:
        return blank(width_mm)
    return f'<span class="acte-filled">{esc(text)}</span>'


def signature_zone(role_label: str, *, signatory_name: str | None = None) -> str:
    """Bloc signature d'un acte : rôle, espace de signature, nom facultatif."""
    name_html = (
        f'<div class="acte-signature-name">{esc(signatory_name)}</div>' if signatory_name else ""
    )
    return f"""
    <div class="acte-signature">
        <div class="acte-signature-role">{esc(role_label)}</div>
        <div class="acte-signature-space"></div>
        {name_html}
    </div>
    """
