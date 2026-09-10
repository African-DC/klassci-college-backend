"""Le code QR d'un lien, en SVG pur Python.

Pourquoi un QR alors que le dépôt sait déjà faire un code 2D
============================================================

`app/services/pdf/_cev.py` rend un Datamatrix, et il continue : c'est la norme
2D-Doc du sceau documentaire, elle se lit avec un lecteur dédié et elle ne se
remplace pas. Le QR répond à une autre exigence, et à une seule : **l'appareil
photo natif d'un téléphone doit savoir le lire**, sans installer d'application.
Aucun téléphone ne décode un Datamatrix depuis son appareil photo par défaut,
et `ppf-datamatrix` ne sait pas produire de QR. Les deux cohabitent donc, chacun
pour son geste — le sceau s'imprime sur un document, le QR s'affiche sur un
écran d'ordinateur pour être scanné par le téléphone d'à côté.

Rendu en SVG, comme le Datamatrix, et pour la même raison
=========================================================

Aucune dépendance image : ni Pillow, ni libdmtx, ni bibliothèque native. `segno`
est du Python pur et rend une matrice de booléens ; le SVG se fabrique ici à la
main. La chaîne produite se pose telle quelle dans une page (elle sort de notre
propre serveur) et WeasyPrint la rastériserait aussi bien, si un document devait
un jour en porter un.

Le piège : `segno.make()` peut rendre un Micro QR
=================================================

`segno.make("ABC12")` rend un **Micro QR** (M2), pas un QR — c'est le format le
plus compact qui contienne la donnée, et c'est précisément ce qu'il ne faut pas
ici : les appareils photo natifs ne le décodent pas. On appelle donc
`make_qr()`, qui garantit un QR de la norme complète même quand la donnée
tiendrait dans plus petit. Un QR qu'aucun téléphone ne lit ne se découvre
autrement qu'en salle des professeurs, un jour de rentrée.

La zone de silence fait quatre modules, pas un
==============================================

Le Datamatrix se contente d'un module de marge blanche ; la norme QR
(ISO/IEC 18004) en exige **quatre**. Un QR posé au bord de son cadre reste
lisible par un scanner patient et échoue sur un appareil photo qu'on tient à
main levée : la marge n'est pas de la décoration, c'est ce que l'algorithme de
détection cherche autour des trois cibles d'angle.
"""

from __future__ import annotations

import segno


def qr_svg(text: str, *, module: int = 4, dark: str = "#0f172a") -> str:
    """Rend `text` en QR SVG (modules sombres sur fond blanc).

    Même signature et même forme de sortie que `datamatrix_svg` : `module` est
    la taille d'un module en pixels, et le fond est blanc opaque. Un QR sombre
    sur fond transparent devient illisible dès que la page passe en thème
    sombre — le contraste doit vivre dans l'image, pas dépendre de ce qu'il y a
    derrière.

    Correction d'erreur : niveau M au minimum. `segno` la remonte d'elle-même
    quand la version choisie le permet sans grandir, donc on demande le plancher
    et on laisse la bibliothèque offrir mieux si c'est gratuit.
    """
    if not text:
        raise ValueError("qr_svg : rien à encoder")

    matrix = segno.make_qr(text, error="m").matrix
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    quiet = 4 * module  # zone de silence normative (ISO/IEC 18004)
    width = cols * module + 2 * quiet
    height = rows * module + 2 * quiet

    # Un rectangle par suite horizontale de modules sombres, et non un par
    # module : la chaîne voyage dans une réponse JSON, là où le Datamatrix est
    # intégré une fois dans un PDF. Le rendu est identique au pixel près.
    rects: list[str] = []
    for r, row in enumerate(matrix):
        colonne = 0
        while colonne < cols:
            if not row[colonne]:
                colonne += 1
                continue
            debut = colonne
            while colonne < cols and row[colonne]:
                colonne += 1
            rects.append(
                f'<rect x="{quiet + debut * module}" y="{quiet + r * module}" '
                f'width="{(colonne - debut) * module}" height="{module}"/>'
            )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges" role="img">'
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
        f'<g fill="{dark}">{"".join(rects)}</g>'
        f"</svg>"
    )
