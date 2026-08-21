"""Des portraits d'annuaire, générés plutôt que collectés.

Une fiche élève sans photo se voit tout de suite en démonstration : la liste
tombe en initiales grises. Aller chercher de vraies photographies poserait un
problème qu'aucune démonstration ne justifie : ce seraient des visages de
personnes réelles dans une base de test. On dessine donc un portrait
d'annuaire : un aplat de couleur, les initiales, rien d'autre.

Les fichiers atterrissent dans le dossier que l'application sert déjà sous
`/uploads`, si bien que la même image s'affiche à l'écran et s'imprime dans les
PDF, qui la relisent depuis le disque.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw

logger = logging.getLogger("klassci.seed")

#: Le dossier monté par `app.main` sous `/uploads`. Le semis tourne sur la même
#: machine que l'application : écrire ici suffit à rendre l'image servable.
UPLOAD_ROOT = Path("/tmp/klassci-uploads")
PHOTO_FOLDER = "portraits"

SIZE = 256

#: Aplats sobres, lisibles en blanc. Pas de dégradé : l'image est réduite à
#: 32 pixels dans une liste, et un dégradé n'y survit pas.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (30, 64, 175),
    (15, 118, 110),
    (146, 64, 14),
    (76, 29, 149),
    (159, 18, 57),
    (22, 101, 52),
    (3, 105, 161),
    (120, 53, 15),
)


def initials(first_name: str, last_name: str) -> str:
    """Les deux lettres qu'on lit sur un badge."""
    first = first_name.strip()[:1].upper() if first_name.strip() else "?"
    last = last_name.strip()[:1].upper() if last_name.strip() else ""
    return f"{first}{last}"


def portrait_url(slug: str, first_name: str, last_name: str) -> str | None:
    """Dessine le portrait s'il n'existe pas et retourne son URL servable.

    Retourne `None` si le disque refuse l'écriture : une photo manquante fait
    retomber l'interface sur les initiales, ce qui reste présentable : alors
    qu'une exception ici arrêterait tout le semis pour une vignette.
    """
    folder = UPLOAD_ROOT / PHOTO_FOLDER
    target = folder / f"{slug}.png"
    url = f"/uploads/{PHOTO_FOLDER}/{slug}.png"

    if target.exists():
        return url

    try:
        folder.mkdir(parents=True, exist_ok=True)
        background = PALETTE[sum(ord(ch) for ch in slug) % len(PALETTE)]
        image = Image.new("RGB", (SIZE, SIZE), background)
        draw = ImageDraw.Draw(image)
        text = initials(first_name, last_name)
        box = draw.textbbox((0, 0), text)
        scale = 6
        draw.text(
            ((SIZE - (box[2] - box[0]) * scale) / 2, (SIZE - (box[3] - box[1]) * scale) / 2),
            text,
            fill=(255, 255, 255),
            font_size=96,
        )
        image.save(target, format="PNG", optimize=True)
    except (OSError, ValueError):
        logger.warning("Portrait non écrit pour %s : la fiche restera en initiales.", slug)
        return None

    return url
