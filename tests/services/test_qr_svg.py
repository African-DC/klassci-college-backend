"""Le code QR, et la seule chose qu'on lui demande : etre lisible par un telephone.

Pourquoi ces tests et pas un decodage
=====================================

Decoder un QR exige une bibliotheque de lecture (zbar, opencv) : des
dependances natives, precisement ce que le rendu SVG existe pour eviter. On
verifie donc la seule chose qu'un decodeur prouverait de plus — que la matrice
produite est bien celle de la donnee — par un chemin sans dependance : le SVG
est relu, sa matrice reconstruite, et comparee a celle que `segno` a calculee.

Restent trois proprietes structurelles qu'aucun decodeur ne verifierait a notre
place, et dont la violation ne se decouvre qu'en salle des professeurs :

1. **Ce n'est pas un Micro QR.** `segno.make()` en produit un des que la donnee
   y tient, et les appareils photo natifs ne le lisent pas. C'est la faute la
   plus facile a commettre ici, et la plus couteuse.
2. **La zone de silence fait quatre modules.** La norme QR l'exige ; le
   Datamatrix d'a cote se contente d'un module, et recopier sa valeur donnerait
   un code que seul un scanner patient decode.
3. **Le fond est opaque.** Un QR sombre sur fond transparent devient illisible
   des que la page passe en theme sombre.
"""

import re

import segno

from app.services.qr_svg import qr_svg

URL = "https://college.klassci.com/televerser/rostan/2vT0hR9kQm-Xz4LpA7bC1dE6fG8hJ0kL2mN4oP6qR8s"

_RECT = re.compile(r'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)"/>')
_DIMENSIONS = re.compile(r'<svg [^>]*width="(\d+)" height="(\d+)"')


def _matrice_du_svg(svg: str, *, module: int, quiet: int, taille: int) -> list[list[int]]:
    """Reconstruit la matrice a partir des rectangles du SVG.

    C'est le decodage que l'on peut se permettre sans dependance native : il ne
    lit pas le contenu du code, il prouve que le dessin correspond exactement a
    la matrice calculee — donc que la fusion des suites horizontales n'a rien
    decale ni perdu.
    """
    grille = [[0] * taille for _ in range(taille)]
    for x, y, largeur, hauteur in _RECT.findall(svg):
        x, y, largeur, hauteur = int(x), int(y), int(largeur), int(hauteur)
        assert hauteur == module, "un rectangle doit tenir sur une seule ligne de modules"
        colonne = (x - quiet) // module
        ligne = (y - quiet) // module
        for decalage in range(largeur // module):
            grille[ligne][colonne + decalage] = 1
    return grille


def test_le_svg_dessine_exactement_la_matrice() -> None:
    """La fusion des suites horizontales ne doit rien deplacer ni oublier."""
    attendue = [list(ligne) for ligne in segno.make_qr(URL, error="m").matrix]
    svg = qr_svg(URL, module=4)

    relue = _matrice_du_svg(svg, module=4, quiet=16, taille=len(attendue))
    assert relue == attendue


def test_ce_n_est_pas_un_micro_qr() -> None:
    """Trois cibles d'angle, donc un QR complet — un Micro QR n'en a qu'une.

    `segno.make()` rendrait un Micro QR sur une donnee courte, et l'appareil
    photo d'un telephone ne le decoderait pas. Le motif de detection fait 7x7
    modules sombres borde de clair, aux trois coins.
    """
    matrice = [list(ligne) for ligne in segno.make_qr("ABC12", error="m").matrix]
    taille = len(matrice)

    assert taille >= 21, "un QR de version 1 fait 21 modules de cote au minimum"
    for ligne, colonne in ((0, 0), (0, taille - 7), (taille - 7, 0)):
        bloc = [rang[colonne : colonne + 7] for rang in matrice[ligne : ligne + 7]]
        assert bloc[0] == [1] * 7, "bord superieur de la cible d'angle"
        assert bloc[6] == [1] * 7, "bord inferieur de la cible d'angle"
        assert bloc[3][2:5] == [1, 1, 1], "coeur de la cible d'angle"


def test_la_zone_de_silence_fait_quatre_modules() -> None:
    """La norme QR l'exige. Un module — la valeur du Datamatrix — ne suffit pas."""
    module = 5
    taille = len(segno.make_qr(URL, error="m").matrix)
    svg = qr_svg(URL, module=module)

    largeur, hauteur = _DIMENSIONS.search(svg).groups()
    assert int(largeur) == int(hauteur) == taille * module + 2 * (4 * module)

    premier = min(int(y) for _, y, _, _ in _RECT.findall(svg))
    assert premier == 4 * module


def test_le_fond_est_opaque() -> None:
    """Sombre sur transparent disparait des que la page passe en theme sombre."""
    svg = qr_svg(URL)
    assert 'fill="#ffffff"' in svg
    assert svg.startswith("<svg") and svg.endswith("</svg>")


def test_deux_liens_differents_donnent_deux_codes_differents() -> None:
    """Garde-fou contre un rendu qui ignorerait son entree."""
    assert qr_svg(URL) != qr_svg(URL + "x")
