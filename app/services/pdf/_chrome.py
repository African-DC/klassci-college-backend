"""Chrome PDF — socle sobre « document officiel » (2026-refonte).

Direction : institutionnel sobre. La typo (Spectral display + Inter corps) et
la hiérarchie portent l'autorité ; la couleur primaire est STRUCTURELLE (filet,
titres, chiffres-clés) et l'accent est réservé à UN point focal par document.
Pas de double cadre, pas de filigrane bruyant, pas de sceau décoratif : le
Sceau numérique institutionnel KLASSCI est l'élément de confiance.

Exporté via `components.py` (aggregator). Ne pas importer ce module
directement depuis les generators : utiliser
`from app.services.pdf import components as ui`.
"""

from __future__ import annotations

from typing import Any

from app.services.pdf._helpers import esc, image_to_datauri
from app.services.pdf.theme import PDFTheme, font_face_css


def base_styles(theme: PDFTheme, *, page_size: str = "A4", margin: str = "16mm 15mm") -> str:
    """Bloc <style> : @font-face + CSS variables + classes utilitaires globales."""
    return f"""
    <style>
        {font_face_css()}
        @page {{ size: {page_size}; margin: {margin}; }}
        :root {{
            --primary: {theme.primary};
            --accent: {theme.accent};
            --ink: {theme.ink};
            --muted: {theme.muted};
            --border: {theme.border};
            --soft-bg: {theme.soft_bg};
            --success: {theme.success};
            --warn: {theme.warn};
            --danger: {theme.danger};
            --font-display: {theme.font_serif};
            --font-body: {theme.font_family};
        }}
        body {{
            font-family: var(--font-body);
            font-size: 10.5px;
            color: var(--ink);
            line-height: 1.45;
            margin: 0;
        }}
        h1, h2, h3 {{ margin: 0; font-family: var(--font-display); font-weight: 700; }}
        a {{ color: var(--primary); text-decoration: none; }}
        strong {{ font-weight: 600; }}
        /* Utilities */
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .muted {{ color: var(--muted); }}
        .accent {{ color: var(--accent); }}
        .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        .emphasis {{ font-weight: 600; color: var(--primary); }}
        .mono {{ font-family: 'Courier New', monospace; font-size: 9px; }}

        /* ============ En-tête : eyebrow RCI + masthead + filet ============ */
        .doc-eyebrow {{
            text-align: center; font-size: 8px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 8px;
        }}
        /* En-tete des documents : une carte, pas une ligne flottante.
           Rayons concentriques — carte 15px, retrait 9px, pastille 6px :
           15 = 6 + 9. Des rayons qui ne s'emboitent pas sont ce qui fait
           qu'un bloc imbrique « sonne faux » sans qu'on sache dire pourquoi. */
        /* Un tableau, pas un flex : WeasyPrint ne rend fiablement ni le
           `gap` ni `overflow:hidden` sur un conteneur flex, et le monogramme
           debordait sa pastille en chevauchant le nom de l'etablissement. */
        .masthead {{
            width: 100%; border-collapse: separate; border-spacing: 0;
            border: 1px solid var(--border);
            border-radius: 15px;
            background: var(--soft-bg);
            margin-bottom: 9px;
        }}
        .masthead > tr > td {{ padding: 9px; vertical-align: middle; }}
        .masthead-logo {{ width: 46px; }}
        .masthead-logo img,
        .masthead-logo .pdf-monogram {{
            width: 46px; height: 46px;
            border-radius: 6px;
            object-fit: contain;
            /* Contour noir pur a faible opacite : une teinte prendrait la
               couleur du fond et se lirait comme une salissure sur le bord. */
            border: 1px solid rgba(0, 0, 0, 0.10);
        }}
        .masthead-id {{ padding-left: 3px; }}
        .masthead-name {{
            font-family: var(--font-display); font-weight: 700;
            font-size: 15px; color: var(--primary); line-height: 1.2;
            letter-spacing: 0.1px;
        }}
        .masthead-meta {{
            font-size: 8px; color: var(--muted); margin-top: 2px; line-height: 1.45;
        }}
        .doc-filet {{
            height: 0; border-bottom: 1.5px solid var(--primary); margin: 0;
        }}
        .doc-filet-soft {{ height: 0; border-bottom: 0.75px solid var(--border); }}

        /* Titre de document */
        .doc-title-block {{ text-align: center; margin: 15px 0 4px; }}
        .doc-title {{
            font-family: var(--font-display); font-weight: 700;
            font-size: 19px; color: var(--ink); letter-spacing: 0.6px;
        }}
        .doc-subtitle {{
            font-size: 11px; color: var(--muted); margin-top: 3px;
        }}
        .doc-number {{
            text-align: right; font-family: 'Courier New', monospace;
            font-size: 8.5px; color: var(--muted); margin-top: 2px;
        }}

        /* Bandeau identité (élève / méta) — filet léger, pas de boîte */
        .pdf-meta-strip {{
            display: flex; justify-content: space-between; gap: 18px;
            padding: 8px 0; margin: 10px 0;
            border-top: 0.75px solid var(--border);
            border-bottom: 0.75px solid var(--border);
            font-size: 10px;
        }}

        /* Titre de section : Inter 600, filet primaire court */
        .pdf-section-title {{
            font-size: 10.5px; font-weight: 600; color: var(--primary);
            text-transform: uppercase; letter-spacing: 0.5px;
            padding-bottom: 4px; margin: 16px 0 9px;
            border-bottom: 1px solid var(--border);
        }}

        /* ============ Tableaux — calmes : en-tête texte + filet primaire ==== */
        .pdf-table {{
            width: 100%; border-collapse: collapse; font-size: 9.5px;
            table-layout: fixed;
        }}
        .pdf-table thead th {{
            background: var(--soft-bg); color: var(--ink);
            padding: 6px 8px; text-align: left; text-transform: uppercase;
            font-size: 8px; letter-spacing: 0.4px; font-weight: 600;
            border-bottom: 1.5px solid var(--primary);
        }}
        .pdf-table tbody td {{
            padding: 5px 8px; border-bottom: 0.75px solid var(--border);
            vertical-align: top; word-wrap: break-word;
        }}
        .pdf-table tbody tr:nth-child(even) td {{ background: var(--soft-bg); }}
        .pdf-table tbody tr.total-row td {{
            background: transparent; border-top: 1.5px solid var(--accent);
            border-bottom: none; font-weight: 700; color: var(--primary);
        }}
        .pdf-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}

        /* Status pills (sémantiques — surtout finance) */
        .pdf-pill {{
            display: inline-block; padding: 1.5px 7px; border-radius: 999px;
            font-size: 8.5px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.3px; white-space: nowrap;
        }}
        .pdf-pill-paid, .pdf-pill-completed, .pdf-pill-valide {{ background: #d1fae5; color: #065f46; }}
        .pdf-pill-partial {{ background: #fef3c7; color: #92400e; }}
        .pdf-pill-pending, .pdf-pill-prospect {{ background: #eef2f6; color: #475569; }}
        .pdf-pill-waived {{ background: #f3e8ff; color: #6b21a8; }}
        .pdf-pill-cancelled, .pdf-pill-rejete, .pdf-pill-failed {{ background: #fee2e2; color: #991b1b; }}
        .pdf-pill-en_validation, .pdf-pill-refunded {{ background: #dbeafe; color: #1e40af; }}

        /* Chiffres-clés : bande compacte plutôt que grosses boîtes KPI */
        .pdf-keyfigures {{
            display: flex; gap: 0; margin: 12px 0;
            border: 0.75px solid var(--border); border-radius: 5px; overflow: hidden;
        }}
        .pdf-keyfigure {{
            flex: 1; padding: 9px 12px; text-align: center;
            border-right: 0.75px solid var(--border);
        }}
        .pdf-keyfigure:last-child {{ border-right: none; }}
        .pdf-keyfigure-label {{
            font-size: 8px; color: var(--muted); text-transform: uppercase;
            letter-spacing: 0.4px;
        }}
        .pdf-keyfigure-value {{
            font-family: var(--font-display); font-size: 18px; font-weight: 700;
            color: var(--primary); margin-top: 3px; font-variant-numeric: tabular-nums;
        }}
        .pdf-keyfigure-value.is-focal {{ color: var(--accent); }}

        /* KPI cards (rétrocompat generators) — allégées */
        .pdf-kpis {{ display: flex; gap: 10px; margin: 8px 0 14px; }}
        .pdf-kpi {{
            flex: 1; padding: 9px 12px; border: 0.75px solid var(--border);
            border-radius: 5px; text-align: center;
        }}
        .pdf-kpi-label {{
            font-size: 8px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .pdf-kpi-value {{
            font-family: var(--font-display); font-size: 16px; font-weight: 700;
            color: var(--primary); margin-top: 3px; font-variant-numeric: tabular-nums;
        }}
        .pdf-kpi-value-accent {{ color: var(--accent); }}
        .pdf-kpi-value-success {{ color: var(--success); }}
        .pdf-kpi-value-warn {{ color: var(--warn); }}

        /* Amount box — sobre : filet accent à gauche, pas de dégradé */
        .pdf-amount-box {{
            padding: 12px 16px; margin: 12px 0;
            border: 0.75px solid var(--border); border-left: 3px solid var(--accent);
            border-radius: 4px; background: var(--soft-bg);
        }}
        .pdf-amount-label {{
            font-size: 9px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.4px;
        }}
        .pdf-amount-value {{
            font-family: var(--font-display); font-size: 22px; font-weight: 700;
            color: var(--primary); margin-top: 3px; font-variant-numeric: tabular-nums;
        }}

        /* Info grid */
        .pdf-info-grid {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px;
            font-size: 10px; margin: 6px 0;
        }}
        .pdf-info-row {{ display: flex; gap: 8px; padding: 2px 0; }}
        .pdf-info-label {{
            color: var(--muted); width: 130px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.2px; font-size: 8.5px;
        }}
        .pdf-info-value {{ flex: 1; color: var(--ink); }}

        /* Info table (label/valeur alignés — table borderless, robuste WeasyPrint) */
        .pdf-info-table {{
            width: 100%; border-collapse: collapse; margin: 8px 0;
            font-size: 11px;
        }}
        .pdf-info-table td {{
            padding: 3.5px 0; vertical-align: top; border: none;
        }}
        .pdf-info-table td.pdf-info-label {{
            width: 32%; white-space: nowrap; padding-right: 14px;
            color: var(--muted); font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.3px; font-size: 8.5px;
            line-height: 1.5;
        }}
        .pdf-info-table td.pdf-info-value {{
            color: var(--ink); font-weight: 500; line-height: 1.4;
        }}

        /* Progress bar */
        .pdf-progress {{
            width: 100%; height: 8px; background: var(--border);
            border-radius: 4px; overflow: hidden; margin: 6px 0 12px;
        }}
        .pdf-progress-fill {{ height: 100%; background: var(--primary); }}

        /* Signatures — colonnes sobres (pas de boîte pointillée) */
        .pdf-signatures {{
            display: flex; justify-content: space-between; gap: 18px;
            margin-top: 26px;
        }}
        .pdf-signature {{ flex: 1; text-align: center; }}
        .pdf-signature-role {{
            color: var(--ink); font-size: 9.5px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .pdf-signature-line {{
            border-top: 0.75px solid var(--ink); margin-top: 42px;
            padding-top: 4px; font-size: 8.5px; color: var(--muted);
        }}

        /* Footer */
        .pdf-footer {{
            margin-top: 20px; padding-top: 9px;
            border-top: 0.75px solid var(--border);
            font-size: 8px; color: var(--muted);
            display: flex; justify-content: space-between; gap: 12px;
        }}
        .pdf-footer-school {{ flex: 1; }}
        .pdf-footer-meta {{ text-align: right; }}
        .pdf-ref {{
            font-family: 'Courier New', monospace; font-size: 8px;
            letter-spacing: 0.5px; color: var(--muted);
        }}

        /* ============ Sceau numérique institutionnel ======================== */
        .pdf-verify {{
            margin-top: 11px; padding: 10px 14px;
            border: 0.75px solid var(--border); border-radius: 5px;
            background: var(--soft-bg);
            display: flex; align-items: center;
        }}
        .pdf-verify-cev {{
            width: 62px; height: 62px; flex: 0 0 62px;
            margin-right: 16px;
            border: 0.75px solid var(--border); border-radius: 3px; background: #fff;
            padding: 2px; box-sizing: border-box;
        }}
        .pdf-verify-cev svg {{ width: 100%; height: 100%; display: block; }}
        .pdf-verify-text {{ font-size: 8.5px; color: var(--muted); line-height: 1.65; }}
        .pdf-verify-text strong {{
            color: var(--primary); font-size: 9px;
            display: inline-block; margin-bottom: 3px;
        }}
        .pdf-verify-url {{
            font-family: 'Courier New', monospace; font-size: 7.5px;
            color: var(--ink); word-break: break-all;
        }}
        .pdf-verify-code {{
            font-family: 'Courier New', monospace; font-size: 12px; font-weight: 700;
            letter-spacing: 1px; color: var(--primary); margin-top: 6px;
        }}

        /* ============ Structure document (sans cadre lourd) ================= */
        .pdf-doc {{ position: relative; }}
        .pdf-doc-header, .pdf-doc-body, .pdf-doc-bottom {{ position: relative; }}
        .pdf-doc-bottom {{ margin-top: 18px; }}
        .pdf-page-body {{ position: relative; }}

        /* Sceau / cachet circulaire (placeholder — opt-in, non utilisé par défaut) */
        .pdf-seal {{
            width: 84px; height: 84px; border: 1.2px solid var(--primary);
            border-radius: 50%; display: flex; align-items: center;
            justify-content: center; text-align: center; color: var(--primary);
            opacity: 0.65;
        }}
        .pdf-seal-text {{
            font-size: 7.5px; font-weight: 700; text-transform: uppercase;
            letter-spacing: 0.8px; line-height: 1.3; padding: 0 8px;
        }}

        /* Monogramme (fallback identité si pas de logo) */
        .pdf-monogram {{
            background: var(--primary); color: #fff;
            display: flex; align-items: center; justify-content: center;
            font-size: 16px; font-weight: 700; letter-spacing: 0.5px;
            font-family: var(--font-display);
        }}
    </style>
    """


# Conservé pour rétrocompat (imports externes éventuels). Non utilisé par le
# nouvel en-tête, qui condense la mention RCI en une seule ligne « eyebrow ».
CI_BANNER_HTML = """
<div class="doc-eyebrow">
    République de Côte d'Ivoire · Union — Discipline — Travail · MENA
</div>
"""


def _eyebrow_html() -> str:
    """Ligne unique RCI/MENA (remplace le bandeau 3 lignes)."""
    return (
        '<div class="doc-eyebrow">République de Côte d\'Ivoire'
        " · Union — Discipline — Travail"
        " · Ministère de l'Éducation Nationale et de l'Alphabétisation</div>"
    )


def premium_header(
    school: dict[str, Any],
    *,
    theme: PDFTheme,
    doc_type: str | None = None,
    doc_subtitle: str | None = None,
    doc_number: str | None = None,
    show_ci_banner: bool = True,
) -> str:
    """En-tête sobre : eyebrow RCI (1 ligne) + masthead + filet + titre document."""
    school = school or {}
    school_name = esc(school.get("school_name", "Établissement"))
    ministry_code = esc(school.get("ministry_code") or "")
    address = esc(school.get("address") or "")
    phone = esc(school.get("phone") or "")
    email = esc(school.get("email") or "")
    logo_data = image_to_datauri(school.get("logo_url"))

    eyebrow = _eyebrow_html() if show_ci_banner else ""

    if logo_data:
        logo_html = f'<img src="{logo_data}" alt="" />'
    else:
        words = [w for w in (school.get("school_name") or "E").split() if w]
        initials = "".join(w[0] for w in words[:2]).upper() or "E"
        logo_html = f'<div class="pdf-monogram">{esc(initials)}</div>'

    # Méta condensée : 2 lignes max (adresse ; code · contact)
    meta_lines: list[str] = []
    if address:
        meta_lines.append(address)
    line2 = " · ".join(
        p
        for p in (
            f"Code MENA : {ministry_code}" if ministry_code else "",
            phone,
            email,
        )
        if p
    )
    if line2:
        meta_lines.append(line2)
    meta_html = f'<div class="masthead-meta">{"<br/>".join(meta_lines)}</div>' if meta_lines else ""

    masthead = f"""
    <table class="masthead"><tr>
        <td class="masthead-logo">{logo_html}</td>
        <td class="masthead-id">
            <div class="masthead-name">{school_name}</div>
            {meta_html}
        </td>
    </tr></table>
    """

    title_block = ""
    if doc_type:
        subtitle_html = (
            f'<div class="doc-subtitle">{esc(doc_subtitle)}</div>' if doc_subtitle else ""
        )
        title_block += f"""
        <div class="doc-title-block">
            <div class="doc-title">{esc(doc_type)}</div>
            {subtitle_html}
        </div>
        """
    if doc_number:
        title_block += f'<div class="doc-number">{esc(doc_number)}</div>'

    return f"""
    {eyebrow}
    {masthead}
    {title_block}
    """


def premium_footer(
    school: dict[str, Any],
    *,
    theme: PDFTheme,
    note: str | None = None,
    reference: str | None = None,
    cev_svg: str | None = None,
    seal_code: str | None = None,
    verify_url: str | None = None,
    manual_verify_url: str | None = None,
) -> str:
    """Footer : école compacte à gauche + réf/note à droite, précédé du sceau.

    `reference` : numéro de référence (officialisant, en mono).
    `cev_svg` + `seal_code` + `verify_url` ajoute le sceau institutionnel
    (Datamatrix + code + URL publique) aux documents vérifiables.
    """
    school = school or {}
    pieces: list[str] = []
    if school.get("school_name"):
        pieces.append(f"<strong>{esc(school['school_name'])}</strong>")
    if school.get("address"):
        pieces.append(esc(school["address"]))
    contact = " · ".join(esc(school.get(k)) for k in ("phone", "email", "website") if school.get(k))
    if contact:
        pieces.append(contact)
    school_block = "<br/>".join(pieces) if pieces else ""

    meta_parts: list[str] = []
    if reference:
        meta_parts.append(f'<div class="pdf-ref">Réf. {esc(reference)}</div>')
    if note:
        meta_parts.append(esc(note))
    meta_block = "<br/>".join(meta_parts)

    verify_block = ""
    if cev_svg:
        verify_block = f"""
    <div class="pdf-verify">
        <div class="pdf-verify-cev">{cev_svg}</div>
        <div class="pdf-verify-text">
            <strong>Sceau numérique institutionnel KLASSCI</strong><br/>
            Scannez le cachet ou vérifiez sur <span class="pdf-verify-url">{esc(manual_verify_url or verify_url or "")}</span>
            en saisissant le code&nbsp;:
            <div class="pdf-verify-code">{esc(seal_code or "")}</div>
        </div>
    </div>"""

    return f"""
    {verify_block}
    <div class="pdf-footer">
        <div class="pdf-footer-school">{school_block}</div>
        <div class="pdf-footer-meta">{meta_block}</div>
    </div>
    """


def document_frame(
    *,
    theme: PDFTheme,
    header_html: str,
    body_html: str,
    bottom_html: str,
    watermark_text: str | None = None,
) -> str:
    """Assemble un document en 3 zones (en-tête / corps / bas), sobre.

    Refonte 2026 : plus de cadre double ni de filigrane (ils créaient du fouillis
    et une moitié de page encadrée vide). Le bas suit le corps naturellement ;
    l'espace restant en pied est du blanc franc, pas une zone encadrée vide.
    `watermark_text` conservé pour compat mais volontairement ignoré.
    """
    _ = watermark_text  # compat de signature — filigrane retiré (direction sobre)
    return f"""
    <div class="pdf-doc">
        <div class="pdf-doc-header">{header_html}</div>
        <div class="pdf-doc-body">{body_html}</div>
        <div class="pdf-doc-bottom">{bottom_html}</div>
    </div>
    """


def seal_block(*, theme: PDFTheme, label: str = "Cachet de l'établissement") -> str:
    """Sceau/cachet circulaire (placeholder officiel, thémé couleur primaire)."""
    return f'<div class="pdf-seal"><span class="pdf-seal-text">{esc(label)}</span></div>'


def signatory_clause(head_master_name: str, head_master_title: str) -> str:
    """« Je soussigné(e), <Nom>, <Titre> » — sans doublon si nom == titre."""
    name = (head_master_name or "").strip()
    title = (head_master_title or "").strip() or "Le Chef d'Établissement"
    if name and name != title:
        return f"Je soussigné(e), <strong>{esc(name)}</strong>, {esc(title)}"
    return f"Je soussigné(e), <strong>{esc(title)}</strong>"


def page_decoration(*, theme: PDFTheme, watermark_text: str | None = None) -> str:
    """Décoration de page pour les documents multi-pages.

    Refonte 2026 : plus de cadre fixe ni de filigrane répétés (source du fouillis
    sur les grandes tables). Les `<thead>` se répètent nativement sous WeasyPrint,
    le footer et le masthead suffisent à cadrer. Renvoie "" (aucune décoration) ;
    conservé pour compat de signature avec les generators multi-pages.
    """
    _ = (theme, watermark_text)
    return ""


def signature_block(roles: list[dict[str, Any]], *, theme: PDFTheme) -> str:
    """Bloc signatures (1 à 4 rôles), colonnes sobres."""
    if not roles:
        return ""
    cards: list[str] = []
    for r in roles:
        role_label = esc(r.get("role", ""))
        name = esc(r.get("name") or "")
        subline = esc(r.get("subline") or "")
        cards.append(
            f"""
            <div class="pdf-signature">
                <div class="pdf-signature-role">{role_label}</div>
                <div class="pdf-signature-line">{name}{(" — " + subline) if subline else ""}</div>
            </div>
            """
        )
    return f'<div class="pdf-signatures">{"".join(cards)}</div>'
