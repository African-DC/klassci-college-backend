"""Chrome PDF — base styles + RCI banner + premium header + footer + signatures.

Exporté via `components.py` (aggregator). Ne pas importer ce module
directement depuis les generators : utiliser
`from app.services.pdf import components as ui`.
"""

from __future__ import annotations

from typing import Any

from app.services.pdf._helpers import esc, image_to_datauri
from app.services.pdf.theme import PDFTheme


def base_styles(theme: PDFTheme, *, page_size: str = "A4", margin: str = "15mm") -> str:
    """Bloc <style> avec CSS variables + classes utilitaires globales."""
    return f"""
    <style>
        @page {{ size: {page_size}; margin: {margin}; }}
        html {{ height: 100%; }}
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
        }}
        body {{
            font-family: {theme.font_family};
            font-size: 11px;
            color: var(--ink);
            line-height: 1.45;
            height: 100%;
            margin: 0;
        }}
        h1, h2, h3 {{ margin: 0; }}
        a {{ color: var(--primary); text-decoration: none; }}
        /* Utilities */
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .muted {{ color: var(--muted); }}
        .accent {{ color: var(--accent); }}
        .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        .emphasis {{ font-weight: 600; color: var(--primary); }}
        .mono {{ font-family: 'Courier New', monospace; font-size: 9px; }}
        /* Section title : border-bottom primary + uppercase */
        .pdf-section-title {{
            font-size: 12px; font-weight: 700; color: var(--primary);
            text-transform: uppercase; letter-spacing: 0.4px;
            border-bottom: 2px solid var(--primary); padding-bottom: 3px;
            margin: 16px 0 10px;
        }}
        /* Premium table — zebra + accent header */
        .pdf-table {{ width: 100%; border-collapse: collapse; font-size: 10px; }}
        .pdf-table thead th {{
            background: var(--primary); color: white; padding: 6px 8px;
            text-align: left; text-transform: uppercase; font-size: 9px;
            letter-spacing: 0.3px; font-weight: 600;
        }}
        .pdf-table tbody td {{
            padding: 6px 8px; border-bottom: 1px solid var(--border);
        }}
        .pdf-table tbody tr:nth-child(even) td {{ background: var(--soft-bg); }}
        .pdf-table tbody tr.total-row td {{
            background: rgba(245, 130, 32, 0.08);
            border-top: 2px solid var(--accent);
            font-weight: 700; color: var(--primary);
        }}
        /* Status pills (sémantiques cohérentes FE Tailwind) */
        .pdf-pill {{
            display: inline-block; padding: 2px 8px; border-radius: 999px;
            font-size: 9px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.3px; white-space: nowrap;
        }}
        .pdf-pill-paid, .pdf-pill-completed, .pdf-pill-valide {{ background: #d1fae5; color: #065f46; }}
        .pdf-pill-partial {{ background: #fef3c7; color: #92400e; }}
        .pdf-pill-pending, .pdf-pill-prospect {{ background: #e2e8f0; color: #475569; }}
        .pdf-pill-waived {{ background: #f3e8ff; color: #6b21a8; }}
        .pdf-pill-cancelled, .pdf-pill-rejete, .pdf-pill-failed {{ background: #fee2e2; color: #991b1b; }}
        .pdf-pill-en_validation, .pdf-pill-refunded {{ background: #dbeafe; color: #1e40af; }}
        /* KPI cards */
        .pdf-kpis {{ display: flex; gap: 10px; margin: 8px 0 14px; }}
        .pdf-kpi {{
            flex: 1; padding: 10px 12px; border: 1px solid var(--border);
            border-radius: 6px; background: var(--soft-bg); text-align: center;
        }}
        .pdf-kpi-label {{
            font-size: 9px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .pdf-kpi-value {{
            font-size: 16px; font-weight: 700; color: var(--primary);
            margin-top: 4px; font-variant-numeric: tabular-nums;
        }}
        .pdf-kpi-value-accent {{ color: var(--accent); }}
        .pdf-kpi-value-success {{ color: var(--success); }}
        .pdf-kpi-value-warn {{ color: var(--warn); }}
        /* Amount box (montant principal premium gradient) */
        .pdf-amount-box {{
            text-align: center; padding: 14px; margin: 10px 0;
            border: 2px solid var(--primary); border-radius: 8px;
            background: linear-gradient(135deg, var(--soft-bg) 0%, #eef2ff 100%);
        }}
        .pdf-amount-label {{
            font-size: 10px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 0.4px;
        }}
        .pdf-amount-value {{
            font-size: 22px; font-weight: 700; color: var(--primary);
            margin-top: 4px; font-variant-numeric: tabular-nums;
        }}
        /* Info grid */
        .pdf-info-grid {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px;
            font-size: 10px; margin: 6px 0;
        }}
        .pdf-info-row {{ display: flex; gap: 8px; padding: 2px 0; }}
        .pdf-info-label {{
            color: var(--muted); width: 130px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.2px; font-size: 9px;
        }}
        .pdf-info-value {{ flex: 1; color: var(--ink); }}
        /* Progress bar */
        .pdf-progress {{
            width: 100%; height: 10px; background: var(--border);
            border-radius: 5px; overflow: hidden; margin: 6px 0 12px;
        }}
        .pdf-progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--accent));
        }}
        /* Signatures (premium dashed cards) */
        .pdf-signatures {{
            display: flex; justify-content: space-between; gap: 14px;
            margin-top: 28px;
        }}
        .pdf-signature {{
            flex: 1; text-align: center; padding: 12px;
            border: 1px dashed var(--border); border-radius: 6px;
        }}
        .pdf-signature-role {{
            color: var(--muted); font-size: 10px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.3px;
        }}
        .pdf-signature-line {{
            border-top: 1px solid var(--ink); margin-top: 44px;
            padding-top: 4px; font-size: 9px; color: var(--muted);
        }}
        /* Footer note */
        .pdf-footer {{
            margin-top: 22px; padding-top: 10px;
            border-top: 1px solid var(--border);
            font-size: 8.5px; color: var(--muted);
            display: flex; justify-content: space-between; gap: 10px;
        }}
        .pdf-footer-school {{ flex: 1; }}
        .pdf-footer-meta {{ text-align: right; }}
        .pdf-ref {{
            font-family: 'Courier New', monospace; font-size: 8.5px;
            letter-spacing: 0.5px; color: var(--muted);
        }}
        /* Cachet Électronique Visible (Datamatrix + code CEV) — docs officiels */
        .pdf-verify {{
            margin-top: 18px; padding: 8px 12px;
            border: 1px solid var(--border); border-radius: 6px;
            background: var(--soft-bg);
            display: flex; align-items: center; gap: 12px;
        }}
        .pdf-verify-cev {{
            width: 72px; height: 72px; flex: 0 0 72px;
            border: 1px solid var(--border); border-radius: 4px; background: #fff;
            padding: 2px; box-sizing: border-box;
        }}
        .pdf-verify-cev svg {{ width: 100%; height: 100%; display: block; }}
        .pdf-verify-text {{
            font-size: 9px; color: var(--muted); line-height: 1.5;
        }}
        .pdf-verify-text strong {{ color: var(--primary); font-size: 9.5px; }}
        .pdf-verify-url {{
            font-family: 'Courier New', monospace; font-size: 8px;
            color: var(--ink); word-break: break-all;
        }}
        .pdf-verify-code {{
            font-family: 'Courier New', monospace; font-size: 12px; font-weight: 700;
            letter-spacing: 1px; color: var(--primary); margin-top: 3px;
        }}
        /* ============ Cadre document officiel (opt-in via document_frame) ===== */
        .pdf-doc {{
            position: relative; box-sizing: border-box;
            border: 2.5px solid var(--primary); border-radius: 4px;
            padding: 13mm 12mm 9mm; height: 100%;
            display: flex; flex-direction: column; overflow: hidden;
        }}
        .pdf-doc::after {{
            content: ""; position: absolute; top: 4px; left: 4px;
            right: 4px; bottom: 4px; border: 0.8px solid var(--primary);
            opacity: 0.35; pointer-events: none;
        }}
        .pdf-doc-header, .pdf-doc-body, .pdf-doc-bottom {{ position: relative; z-index: 1; }}
        .pdf-doc-body {{ flex: 1; }}
        .pdf-doc-bottom {{ margin-top: auto; }}
        /* Filigrane diagonal discret (nom de l'école) */
        .pdf-watermark {{
            position: absolute; top: 50%; left: 50%;
            transform: translate(-50%, -50%) rotate(-32deg);
            font-family: var(--font-serif, Georgia, serif);
            font-size: 30px; font-weight: 700; letter-spacing: 1px;
            color: var(--primary); opacity: 0.13; white-space: nowrap;
            text-transform: uppercase; text-align: center; z-index: 0;
        }}
        /* Décoration de page répétée (cadre + filigrane FIXES) — pour les
           documents multi-pages (liste de classe, bordereau, EDT, PV). Se
           répète automatiquement sur chaque page sans rogner le contenu. */
        .pdf-page-frame {{
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            border: 2.5px solid var(--primary); border-radius: 4px;
            pointer-events: none; z-index: 0;
        }}
        .pdf-page-frame::after {{
            content: ""; position: absolute; top: 4px; left: 4px;
            right: 4px; bottom: 4px; border: 0.8px solid var(--primary);
            opacity: 0.35;
        }}
        .pdf-page-watermark {{
            position: fixed; top: 50%; left: 50%;
            transform: translate(-50%, -50%) rotate(-32deg);
            font-family: var(--font-serif, Georgia, serif);
            font-size: 30px; font-weight: 700; letter-spacing: 1px;
            color: var(--primary); opacity: 0.13; white-space: nowrap;
            text-transform: uppercase; text-align: center; z-index: 0;
        }}
        /* Contenu au-dessus de la décoration fixe */
        .pdf-page-body {{ position: relative; z-index: 1; padding: 4mm 3mm; }}
        /* Sceau / cachet circulaire (placeholder officiel) */
        .pdf-seal {{
            width: 92px; height: 92px; border: 1.5px solid var(--primary);
            border-radius: 50%; display: flex; align-items: center;
            justify-content: center; text-align: center; color: var(--primary);
            opacity: 0.6; position: relative;
        }}
        .pdf-seal::before {{
            content: ""; position: absolute; inset: 4px;
            border: 0.8px solid var(--primary); border-radius: 50%;
        }}
        .pdf-seal-text {{
            font-size: 8px; font-weight: 700; text-transform: uppercase;
            letter-spacing: 1px; line-height: 1.3; padding: 0 8px;
        }}
        /* Monogramme (fallback identité si pas de logo) */
        .pdf-monogram {{
            width: 64px; height: 64px; border-radius: 50%;
            background: var(--primary); color: #fff; display: flex;
            align-items: center; justify-content: center; font-size: 22px;
            font-weight: 700; letter-spacing: 1px;
            font-family: var(--font-serif, Georgia, serif);
        }}
    </style>
    """


CI_BANNER_HTML = """
<div style="text-align:center; margin-bottom:8px; color:#334155;">
    <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.4px;">
        République de Côte d'Ivoire
    </div>
    <div style="font-size:9px; font-style:italic; margin-bottom:3px;">
        Union &mdash; Discipline &mdash; Travail
    </div>
    <div style="font-size:9px;">
        Ministère de l'Éducation Nationale et de l'Alphabétisation
    </div>
</div>
"""


def premium_header(
    school: dict[str, Any],
    *,
    theme: PDFTheme,
    doc_type: str | None = None,
    doc_subtitle: str | None = None,
    doc_number: str | None = None,
    show_ci_banner: bool = True,
) -> str:
    """Bandeau premium : banner RCI + logo + nom + code + adresse + doc type."""
    school = school or {}
    school_name = esc(school.get("school_name", "Établissement"))
    ministry_code = esc(school.get("ministry_code") or "")
    address = esc(school.get("address") or "")
    phone = esc(school.get("phone") or "")
    email = esc(school.get("email") or "")
    motto = esc(school.get("motto") or "")
    logo_data = image_to_datauri(school.get("logo_url"))

    ci = CI_BANNER_HTML if show_ci_banner else ""

    if logo_data:
        logo_html = (
            f'<img src="{logo_data}" alt="Logo" '
            f'style="max-height:72px; max-width:160px; object-fit:contain;" />'
        )
    else:
        # Fallback identité : monogramme circulaire avec les initiales de l'école
        # (évite un en-tête nu quand le tenant n'a pas encore uploadé son logo).
        words = [w for w in (school.get("school_name") or "E").split() if w]
        initials = "".join(w[0] for w in words[:2]).upper() or "E"
        logo_html = f'<div class="pdf-monogram">{esc(initials)}</div>'

    contact_lines: list[str] = []
    if address:
        contact_lines.append(esc(address))
    contact_pieces = [p for p in (phone, email) if p]
    if contact_pieces:
        contact_lines.append(" · ".join(contact_pieces))
    contact_html = (
        '<div style="font-size:9px; color:var(--muted); margin-top:2px;">'
        + "<br/>".join(contact_lines)
        + "</div>"
        if contact_lines
        else ""
    )

    code_html = (
        f'<div style="font-size:9px; color:var(--muted); margin-top:2px;">'
        f"Code MENA : <strong>{ministry_code}</strong></div>"
        if ministry_code
        else ""
    )

    motto_html = (
        f'<div style="font-size:9px; font-style:italic; color:var(--accent); '
        f'margin-top:3px;">« {motto} »</div>'
        if motto
        else ""
    )

    header_block = f"""
    <div style="display:flex; align-items:center; gap:14px; margin-bottom:6px;
                padding-bottom:8px; border-bottom:1px solid var(--border);">
        <div style="flex:0 0 auto;">{logo_html}</div>
        <div style="flex:1; text-align:center;">
            <div style="font-size:15px; font-weight:700; color:var(--primary);
                        letter-spacing:0.3px;">
                {school_name}
            </div>
            {code_html}
            {contact_html}
            {motto_html}
        </div>
    </div>
    """

    title_block = ""
    if doc_type or doc_number:
        type_html = (
            f'<h1 style="font-size:17px; color:var(--primary); '
            f'letter-spacing:0.8px; margin:8px 0 2px;">{esc(doc_type)}</h1>'
            if doc_type
            else ""
        )
        subtitle_html = (
            f'<div style="font-size:11px; color:var(--accent); '
            f'font-weight:600; margin-bottom:6px;">{esc(doc_subtitle)}</div>'
            if doc_subtitle
            else ""
        )
        number_html = (
            f'<div style="text-align:right; font-size:9px; '
            f'color:var(--muted); margin-bottom:6px;">{esc(doc_number)}</div>'
            if doc_number
            else ""
        )
        title_block = f"""
        <div style="text-align:center; margin: 6px 0 10px;">
            {type_html}
            {subtitle_html}
        </div>
        {number_html}
        """

    return f"""
    {ci}
    {header_block}
    {title_block}
    """


def premium_footer(
    school: dict[str, Any],
    *,
    theme: PDFTheme,
    note: str | None = None,
    reference: str | None = None,
    cev_svg: str | None = None,
    cev_code: str | None = None,
    verify_url: str | None = None,
) -> str:
    """Footer : adresse école compacte à gauche + note/réf/date à droite.

    `reference` : numéro de référence du document (officialisant, affiché en
    mono au-dessus de la note légale).
    `cev_svg` + `cev_code` + `verify_url` : si fournis, ajoute le **Cachet
    Électronique Visible** (Datamatrix + code CEV lisible + URL publique)
    au-dessus du pied de page — pour les documents officiels vérifiables.
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
            <strong>Cachet Électronique Visible (CEV)</strong><br/>
            Scannez le cachet ou vérifiez sur <span class="pdf-verify-url">{esc(verify_url or "")}</span>
            en saisissant le code&nbsp;:
            <div class="pdf-verify-code">{esc(cev_code or "")}</div>
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
    """Cadre de document officiel : bordure double + filigrane + remplir-la-page.

    Structure en 3 zones (flex column) : en-tête, corps (flex:1) et bas de page
    (poussé au pied via margin-top:auto). Évite la moitié de page vide des docs
    d'une page (certificat, attestation). Le filigrane (nom de l'école) est en
    fond, faible opacité. Thémé par les couleurs du tenant via les CSS variables
    de `base_styles`. Réutilisable par tous les générateurs.
    """
    # Filigrane en position:fixed (au niveau de la page) — plus fiable que
    # absolute dans le flex container (et non rogné par overflow:hidden).
    watermark = (
        f'<div class="pdf-page-watermark">{esc(watermark_text)}</div>' if watermark_text else ""
    )
    return f"""
    {watermark}
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
    """« Je soussigné(e), <Nom>, <Titre> » — sans doublon si nom == titre.

    Partagé par les documents officiels signés (certificat, attestation…).
    Quand le nom du chef d'établissement n'est pas renseigné, le BE retombe sur
    le titre pour les deux champs : on n'affiche alors qu'une seule fois le
    titre au lieu de le répéter.
    """
    name = (head_master_name or "").strip()
    title = (head_master_title or "").strip() or "Le Chef d'Établissement"
    if name and name != title:
        return f"Je soussigné(e), <strong>{esc(name)}</strong>, {esc(title)}"
    return f"Je soussigné(e), <strong>{esc(title)}</strong>"


def page_decoration(*, theme: PDFTheme, watermark_text: str | None = None) -> str:
    """Cadre + filigrane FIXES, répétés sur chaque page (documents multi-pages).

    À placer en tout début de `<body>`, AVANT le contenu. Contrairement à
    `document_frame` (cadre plein-page mono-page qui rogne le débordement), ces
    éléments `position: fixed` se répètent sur chaque page sans clipper le
    contenu qui s'étale sur plusieurs pages. Enrober le contenu dans
    `<div class="pdf-page-body">…</div>` pour qu'il passe au-dessus.
    Thémé par la couleur primaire du tenant.
    """
    watermark = (
        f'<div class="pdf-page-watermark">{esc(watermark_text)}</div>' if watermark_text else ""
    )
    return f'<div class="pdf-page-frame"></div>{watermark}'


def signature_block(roles: list[dict[str, Any]], *, theme: PDFTheme) -> str:
    """Bloc signatures dashed cards (1 à 4 rôles)."""
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
