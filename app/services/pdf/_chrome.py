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

    logo_html = (
        f'<img src="{logo_data}" alt="Logo" '
        f'style="max-height:72px; max-width:160px; object-fit:contain;" />'
        if logo_data
        else ""
    )

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


def premium_footer(school: dict[str, Any], *, theme: PDFTheme, note: str | None = None) -> str:
    """Footer : adresse école compacte à gauche + note/date à droite."""
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

    return f"""
    <div class="pdf-footer">
        <div class="pdf-footer-school">{school_block}</div>
        <div class="pdf-footer-meta">{esc(note or "")}</div>
    </div>
    """


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
