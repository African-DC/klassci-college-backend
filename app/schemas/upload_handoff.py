"""Schémas de la reprise de téléversement, côté ordinateur.

Ce que ces schémas laissent volontairement dehors
=================================================

Le **jeton** n'apparaît dans aucune réponse. Il ne vit que dans l'URL du code
QR, et l'ordinateur n'en a jamais besoin : il pilote sa session par
l'identifiant, le téléphone dépose par le jeton. Deux secrets, deux usages, et
l'un ne se déduit pas de l'autre.

L'**état civil** du destinataire n'y figure pas non plus. `label` vaut « Kouadio
A. » — prénom et initiale — parce que le même libellé s'affiche sur un téléphone
que n'importe qui peut avoir en main. C'est assez pour que l'opérateur vérifie
qu'il regarde la bonne session, et pas assez pour identifier un mineur.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

#: Une valeur d'`extras` est un libellé (le type d'une pièce jointe), pas un
#: texte libre : il part dans un hash Redis et revient dans une écriture en base.
_Complement = Annotated[str, StringConstraints(max_length=120)]


class HandoffOpenRequest(BaseModel):
    """Ouvrir une session : ce que l'écran de l'opérateur demande.

    `subject_id` est absent à l'inscription, où la photo est prise avant que la
    fiche existe. La session est alors en mode `stage-only` : le serveur garde
    les octets, ne touche aucune colonne, et l'écran récupère l'image pour la
    donner au formulaire.

    `extras` porte ce que la cible réclame en plus (le type d'une pièce jointe).
    Les clés que la cible ne connaît pas sont ignorées, et une clé manquante est
    refusée ici plutôt qu'à la confirmation — découvrir le manque une fois la
    photo prise reviendrait à la refuser, l'élève reparti.
    """

    target_kind: str
    subject_id: int | None = None
    extras: dict[str, _Complement] = Field(default_factory=dict, max_length=8)


class HandoffSessionState(BaseModel):
    """L'état d'une session, tel que le sondage le relit toutes les deux secondes."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    state: Literal["open", "receiving", "proposed", "done"]
    mode: Literal["finalise", "stage-only"]
    label: str
    metier: str
    expires_at: datetime
    retakes_left: int
    staged_mime: str | None = None


class HandoffSessionOpened(HandoffSessionState):
    """La réponse d'une ouverture : de quoi peindre le code QR et prévenir.

    `qr_svg` est une chaîne SVG produite par notre propre serveur, à poser telle
    quelle dans la page. `url` est le même lien en clair, pour qui préfère le
    taper que le scanner.

    `warnings` dit ce qui empêchera le téléphone d'arriver au bout — une adresse
    publique qui ne sort pas du réseau local, un site en HTTP où la caméra
    directe n'existe pas. Vide dans une configuration saine.
    """

    url: str
    qr_svg: str
    accepts: list[str]
    max_bytes: int
    warnings: list[str] = Field(default_factory=list)


class HandoffConfirmed(BaseModel):
    """Le dépôt est écrit : l'URL publique du fichier, désormais servi."""

    state: Literal["done"] = "done"
    url: str


class HandoffRetaken(BaseModel):
    """« Reprendre » : la session rouvre, l'échéance ne bouge pas."""

    state: Literal["open"] = "open"
    retakes_left: int
