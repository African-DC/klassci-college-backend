"""Ce que le produit a gagné, du côté serveur.

Le portail affiche « Nouveautés » à partir de deux moitiés : la sienne, qu'il
embarque, et celle-ci. Sans cet endpoint, le modal ne parlerait que des écrans
et tairait tout ce qui a changé dans les calculs, les documents et les droits —
c'est-à-dire l'essentiel de ce qu'une école remarque.

Le fichier servi est la projection du changelog produite par
`scripts/release_feed.py`. On ne le recalcule pas ici : le lire à chaque appel
depuis le Markdown ferait dépendre une réponse d'API d'un fichier de
documentation, et le premier changelog mal formé rendrait une erreur 500 sur
une fonctionnalité d'agrément.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from app.core.dependencies import TokenData, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whats-new"])

#: Depuis `app/routers/`, la racine est deux crans plus haut. Le fichier y est
#: copié par le Dockerfile ; en développement il est produit par le script.
_FLUX = Path(__file__).resolve().parent.parent.parent / "RELEASES.json"

#: Ce qu'on rend quand le fichier manque. Une liste vide, pas une erreur : le
#: portail affiche alors « rien de neuf », ce qui est faux mais inoffensif,
#: là où un 500 sur une cloche de nouveautés ferait croire à une panne.
_VIDE: dict[str, Any] = {
    "product": "klassci-college-backend",
    "current_version": None,
    "versions": [],
}


@router.get("/whats-new", summary="Les nouveautes du serveur, telles que le changelog les dit")
async def whats_new(_: TokenData = Depends(get_current_user)) -> dict[str, Any]:
    """Le flux des versions, pour le modal « Nouveautes » du portail.

    Authentifie mais sans droit particulier : chaque role lit ensuite ce qui le
    concerne, et le filtrage par persona se fait a l'ecran. Rien ici n'est
    sensible — ce sont les phrases publiques du changelog.
    """
    try:
        return json.loads(_FLUX.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("RELEASES.json absent : le modal des nouveautes sera vide.")
        return _VIDE
    except (OSError, json.JSONDecodeError):
        logger.exception("RELEASES.json illisible.")
        return _VIDE
