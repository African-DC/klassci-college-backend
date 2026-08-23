"""Feuille de style du reçu en deux exemplaires sur une A4.

La page se découpe en deux moitiés de 148 mm que la caisse sépare aux ciseaux.
Toute la géométrie est ici : hauteurs fermes, débordement coupé, et 1 mm laissé
libre en pied de page pour qu'un arrondi de rendu ne pousse jamais une ligne
sur une seconde feuille, ce qui ruinerait la découpe.

Le contenu d'une moitié suit le flux normal. Deux mises en page de pied collant
ont été essayées et écartées : une table à hauteur fixe, dont WeasyPrint
fragmente la dernière rangée sous le trait de coupe — les signatures
disparaissaient —, et un pied en `position: absolute`, qui fait boucler la mise
en page plus d'une minute par document. Ce qui garantit que le pied reste dans
la moitié n'est donc pas un calage, mais le fait que chaque champ de longueur
variable soit borné en amont (voir `_receipt_parts`).

Utilisé par `receipt.py` seul : ce n'est pas un composant partagé.
"""

from __future__ import annotations

from app.services.pdf.theme import PDFTheme, font_face_css

# 297 mm d'A4 pour deux moitiés : 148 + 148, et 1 mm de réserve.
HALF_HEIGHT_MM = 148.0
PAD_TOP_MM, PAD_SIDE_MM, PAD_BOTTOM_MM = 9.0, 11.0, 7.0
HALF_PADDING = f"{PAD_TOP_MM}mm {PAD_SIDE_MM}mm {PAD_BOTTOM_MM}mm"

# La hauteur qu'un exemplaire ne doit pas dépasser. Sert de repère aux tests
# de mise en page, qui vérifient que le pied du premier exemplaire reste
# au-dessus du trait de coupe.
HALF_CONTENT_MM = HALF_HEIGHT_MM - PAD_TOP_MM - PAD_BOTTOM_MM


def receipt_styles(theme: PDFTheme) -> str:
    """Bloc `<style>` complet du reçu deux exemplaires."""
    mono = "'Courier New', monospace"
    return f"""
    <style>
        {font_face_css()}
        @page {{ size: A4 portrait; margin: 0; }}
        :root {{
            --primary: {theme.primary};
            --accent: {theme.accent};
            --ink: {theme.ink};
            --muted: {theme.muted};
            --border: {theme.border};
            --soft-bg: {theme.soft_bg};
        }}
        body {{
            font-family: {theme.font_family};
            font-size: 10px; color: var(--ink); line-height: 1.4; margin: 0;
        }}

        /* ================= Géométrie de la découpe ====================== */
        .rc-half {{
            height: {HALF_HEIGHT_MM}mm;
            box-sizing: border-box;
            padding: {HALF_PADDING};
            overflow: hidden;
        }}
        /* Le pied suit le corps. Le blanc qui reste jusqu'au trait de coupe
           varie donc avec le nombre de frais listés : c'est la marge dans
           laquelle on donne le coup de ciseaux. */
        .rc-bottom {{ margin-top: 6mm; }}
        .rc-cut {{
            height: 0;
            border-top: 0.75px dashed var(--border);
            position: relative;
        }}
        /* Un recu annule reste imprimable, mais jamais muet. */
        .rc-annule {{
            margin: 4px 0 6px;
            padding: 5px 8px;
            border: 1.4pt solid #b91c1c;
            border-radius: 4px;
            background: #fef2f2;
            color: #7f1d1d;
            font-size: 8pt;
            line-height: 1.35;
        }}
        .rc-annule strong {{ letter-spacing: 0.06em; }}
        .rc-cut-label {{
            position: absolute; top: -5px; left: 43%;
            background: #fff; padding: 0 10px;
            font-size: 7px; color: var(--muted);
            text-transform: uppercase; letter-spacing: 2px;
        }}

        /* ================= En-tête compact =============================== */
        .rc-eyebrow {{
            font-size: 6.5px; color: var(--muted); text-transform: uppercase;
            letter-spacing: 0.8px; text-align: center; margin-bottom: 5px;
        }}
        .rc-head {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .rc-head td {{ vertical-align: middle; padding: 0; border: none; }}
        .rc-head td.rc-head-id {{ padding-right: 10px !important; }}
        /* Largeurs fermes : un nom d'école à rallonge s'enroule dans sa
           colonne au lieu de venir buter contre le titre du document. */
        .rc-head td.rc-doc {{ width: 34%; }}
        .rc-head-logo {{ width: 52px; padding-right: 11px !important; }}
        .rc-head-logo img {{ max-height: 44px; max-width: 52px; }}
        .rc-monogram {{
            width: 40px; height: 40px; border-radius: 5px; background: var(--primary);
            color: #fff; text-align: center; line-height: 40px; font-size: 15px;
            font-weight: 700; font-family: {theme.font_serif};
        }}
        .rc-school {{
            font-family: {theme.font_serif}; font-weight: 700; font-size: 14px;
            color: var(--primary); line-height: 1.15;
        }}
        .rc-school-meta {{ font-size: 7px; color: var(--muted); line-height: 1.45; }}
        .rc-doc {{ text-align: right; white-space: nowrap; }}
        .rc-doc-type {{
            font-family: {theme.font_serif}; font-weight: 700; font-size: 14.5px;
            letter-spacing: 0.5px; color: var(--ink);
        }}
        .rc-doc-num {{
            font-family: {mono}; font-size: 9px; color: var(--muted); margin-top: 2px;
        }}
        .rc-copy {{
            display: inline-block; margin-top: 4px; padding: 1.5px 9px;
            border: 0.75px solid var(--border); border-radius: 999px;
            font-size: 7px; text-transform: uppercase; letter-spacing: 1px;
            color: var(--muted);
        }}
        .rc-filet {{ height: 0; border-bottom: 1.2px solid var(--primary); margin: 6px 0 9px; }}

        /* ================= Deux colonnes ================================ */
        .rc-cols {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .rc-cols > tbody > tr > td {{ vertical-align: top; padding: 0; border: none; }}
        .rc-col-left {{ width: 38%; padding-right: 7mm !important; }}
        .rc-col-right {{ width: 62%; }}

        /* Montant du jour — le point focal, en accent */
        .rc-amount {{
            border: 0.75px solid var(--border); border-left: 3px solid var(--accent);
            border-radius: 3px; background: var(--soft-bg);
            padding: 8px 11px; margin-bottom: 9px;
        }}
        .rc-amount-label {{
            font-size: 7px; text-transform: uppercase; letter-spacing: 0.7px;
            color: var(--muted);
        }}
        .rc-amount-value {{
            font-family: {theme.font_serif}; font-weight: 700; font-size: 21px;
            color: var(--primary); line-height: 1.15; margin-top: 2px;
            white-space: nowrap;
        }}

        /* Bloc identité / moyen de paiement */
        .rc-info {{ width: 100%; border-collapse: collapse; }}
        .rc-info td {{ padding: 2.4px 0; border: none; vertical-align: top; }}
        .rc-info td.rc-info-k {{
            width: 34%; color: var(--muted); font-size: 7px; font-weight: 600;
            text-transform: uppercase; letter-spacing: 0.3px; padding-right: 7px;
            line-height: 1.6;
        }}
        .rc-info td.rc-info-v {{ font-size: 9.5px; }}
        .rc-strong {{ font-weight: 600; }}

        /* ================= Situation financière ========================= */
        .rc-title {{
            font-size: 7.5px; font-weight: 600; color: var(--primary);
            text-transform: uppercase; letter-spacing: 0.7px;
            border-bottom: 0.75px solid var(--border);
            padding-bottom: 3px; margin-bottom: 5px;
        }}
        .rc-sit {{
            width: 100%; border-collapse: collapse; table-layout: fixed;
            font-size: 8.5px;
        }}
        .rc-sit th {{
            background: var(--soft-bg); color: var(--ink);
            font-size: 6.5px; text-transform: uppercase; letter-spacing: 0.4px;
            font-weight: 600; text-align: right; padding: 3px 5px;
            border-bottom: 1px solid var(--primary);
        }}
        .rc-sit th.rc-l, .rc-sit td.rc-l {{ text-align: left; }}
        .rc-sit td {{
            padding: 3px 5px; text-align: right; white-space: nowrap;
            border-bottom: 0.5px solid var(--border);
            font-variant-numeric: tabular-nums;
        }}
        .rc-sit td.rc-l {{ white-space: normal; word-wrap: break-word; }}
        .rc-sit tr.rc-total td {{
            border-top: 1.2px solid var(--accent); border-bottom: none;
            font-weight: 700; color: var(--primary); padding-top: 4px;
        }}
        .rc-sit td.rc-rest {{ font-weight: 600; }}
        .rc-sit tr.rc-total td.rc-rest {{ color: var(--accent); }}
        .rc-note {{ font-size: 7px; color: var(--muted); margin-top: 5px; line-height: 1.5; }}
        .rc-note strong {{ color: var(--ink); font-weight: 600; }}

        /* ================= Chiffres clés ================================ */
        .rc-keys {{
            width: 100%; border-collapse: collapse; margin-top: 10px;
            border: 0.75px solid var(--border); border-radius: 4px;
        }}
        .rc-keys td {{
            width: 33.33%; padding: 6px 10px; text-align: center;
            border: none; border-right: 0.75px solid var(--border);
        }}
        .rc-keys td:last-child {{ border-right: none; }}
        .rc-key-label {{
            font-size: 6.5px; color: var(--muted); text-transform: uppercase;
            letter-spacing: 0.7px;
        }}
        .rc-key-value {{
            font-family: {theme.font_serif}; font-weight: 700; font-size: 13.5px;
            color: var(--primary); margin-top: 2px; white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }}
        .rc-key-value.rc-focal {{ color: var(--accent); }}

        /* ================= Pied de moitié =============================== */
        .rc-sign {{ width: 100%; border-collapse: collapse; }}
        .rc-sign td {{
            border: none; padding: 0 12px; text-align: center; width: 50%;
            vertical-align: top;
        }}
        .rc-sign-role {{
            font-size: 7px; font-weight: 600; text-transform: uppercase;
            letter-spacing: 0.5px; color: var(--ink);
        }}
        .rc-sign-line {{
            border-top: 0.75px solid var(--ink); margin-top: 20px;
            padding-top: 3px; font-size: 7px; color: var(--muted);
        }}
        .rc-foot {{
            width: 100%; border-collapse: collapse;
            margin-top: 7px; padding-top: 4px;
            border-top: 0.5px solid var(--border);
            font-size: 6.5px; color: var(--muted);
        }}
        .rc-foot td {{ border: none; padding: 0; vertical-align: top; }}
        .rc-foot td.rc-foot-right {{
            text-align: right; white-space: nowrap; font-family: {mono};
        }}
    </style>
    """
