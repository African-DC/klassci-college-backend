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

#: Combien d'entrees par section. Le meme nombre que la tranche du portail :
#: les deux moities de la fenetre doivent peser pareil, sinon l'une noie
#: l'autre.
PAR_SECTION = 6

#: Ce qu'on rend quand le fichier manque. Une liste vide, pas une erreur : le
#: portail affiche alors « rien de neuf », ce qui est faux mais inoffensif,
#: la ou un 500 sur une cloche de nouveautes ferait croire a une panne.
_VIDE: dict[str, Any] = {
    "product": "klassci-college-backend",
    "generated_at": "",
    "version": None,
    "released": False,
    "total": 0,
    "sections": {},
}


def _tranche(flux: dict[str, Any]) -> dict[str, Any]:
    """La version la plus recente, bornee a ce qui se lit.

    La decoupe se fait ici, et non a l'ecran. Le flux entier pese cent trente
    kilo-octets : les envoyer pour que le portable en jette quatre-vingt-quinze
    pour cent serait payer une 3G pour rien. C'est aussi la seule facon que la
    regle — combien d'entrees, dans quel ordre — n'existe qu'a un endroit par
    cote du fil.
    """
    versions = flux.get("versions") or []
    recente = versions[0] if versions else {}
    toutes = recente.get("sections") or {}
    return {
        "product": flux.get("product", ""),
        "generated_at": flux.get("generated_at", ""),
        "version": recente.get("version"),
        "released": recente.get("released", False),
        # Ce qu'on laisse de cote, pour que l'ecran puisse le dire au lieu de
        # laisser croire qu'il montre tout.
        "total": sum(len(lignes) for lignes in toutes.values()),
        "sections": {nom: lignes[:PAR_SECTION] for nom, lignes in toutes.items() if lignes},
    }


@router.get("/whats-new", summary="Les nouveautes du serveur, telles que le changelog les dit")
async def whats_new(_: TokenData = Depends(get_current_user)) -> dict[str, Any]:
    """Le flux des versions, pour le modal « Nouveautes » du portail.

    Authentifie mais sans droit particulier : chaque role lit ensuite ce qui le
    concerne, et le filtrage par persona se fait a l'ecran. Rien ici n'est
    sensible — ce sont les phrases publiques du changelog.

    Rend la meme forme que `public/whats-new.json` du portail, pour que la
    fenetre assemble deux moities identiques sans rien recalculer.
    """
    try:
        return _tranche(json.loads(_FLUX.read_text(encoding="utf-8")))
    except FileNotFoundError:
        logger.warning("RELEASES.json absent : le modal des nouveautes sera vide.")
        return _VIDE
    except (OSError, json.JSONDecodeError):
        logger.exception("RELEASES.json illisible.")
        return _VIDE
