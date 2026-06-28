"""Cachet Électronique Visible (CEV) — Datamatrix en SVG pur Python.

Le CEV suit le principe du 2D-Doc : un code-barres 2D Datamatrix (symbologie
des documents officiels, plus robuste qu'un QR pour ce cas d'usage) qui, scanné,
ouvre la page de vérification publique. La preuve cryptographique (signature
Ed25519) est portée par le code CEV lisible imprimé à côté (voir
`document_issuance_service`).

Rendu en SVG inline : WeasyPrint le rasterise nativement, donc aucune dépendance
image (Pillow, libdmtx…) n'est requise.
"""

from __future__ import annotations

from ppf.datamatrix import DataMatrix


def datamatrix_svg(text: str, *, module: int = 4, dark: str = "#0f172a") -> str:
    """Rend `text` en Datamatrix SVG (modules sombres sur fond blanc).

    `module` = taille d'un module en px. Noir sur blanc pour un contraste de
    lecture optimal à l'impression (les scanners 2D-Doc l'exigent).
    """
    matrix = DataMatrix(text).matrix
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    quiet = module  # marge blanche d'un module autour (zone de silence)
    width = cols * module + 2 * quiet
    height = rows * module + 2 * quiet

    rects: list[str] = []
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            if bit:
                x = quiet + c * module
                y = quiet + r * module
                rects.append(f'<rect x="{x}" y="{y}" width="{module}" height="{module}"/>')

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
        f'<g fill="{dark}">{"".join(rects)}</g>'
        f"</svg>"
    )
