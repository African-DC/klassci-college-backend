"""Schémas de l'écran « Dettes d'un exercice précédent ».

## Pourquoi les deux champs sont obligatoires

`update_school_info` fait `model_dump(exclude_none=True)` : un champ envoyé à
`null` y est silencieusement jeté. `fee_service.update_fee_variant` a dû passer
à `exclude_unset` pour cette raison précise — une portée posée par erreur ne se
retirait plus jamais depuis l'écran, le formulaire acceptait le choix et il ne
se passait rien.

Ici, ni l'un ni l'autre : les deux champs sont **requis**. Les deux colonnes
sont NOT NULL, `null` n'y est donc jamais une valeur légitime, et un PUT sur
`/admin/arrears-policy` énonce la politique entière — c'est un réglage à deux
commandes, un écran qui en montre une sans l'autre n'existe pas. Un corps
incomplet sort en 422, jamais en écriture partielle silencieuse : la question
« qu'est-ce que le serveur a fait de mon champ manquant » ne se pose plus.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.models.academic import ArrearsPolicy

#: La colonne est un `INT UNSIGNED` en production. Au-delà, MySQL refuse avec
#: une erreur de pilote illisible ; la borne la transforme en 422 lisible.
SEUIL_MAX_XOF = 4_294_967_295


class ArrearsPolicyResponse(BaseModel):
    """L'état du réglage, dans le vocabulaire des colonnes.

    Même nom du formulaire à la base au journal d'audit : une trace se relit
    des mois plus tard, et traduire en chemin est le meilleur moyen de croiser
    deux champs qui ne parlent pas de la même chose.
    """

    model_config = ConfigDict(from_attributes=True)

    arrears_policy: ArrearsPolicy
    arrears_block_threshold_xof: int


class ArrearsPolicyUpdate(BaseModel):
    """La politique entière, énoncée d'un coup. Voir l'en-tête du module."""

    arrears_policy: ArrearsPolicy
    #: Le seuil vaut aussi sous `off` et `inform` : la direction le fixe une
    #: fois, et un aller-retour par `inform` ne le lui reprend pas.
    arrears_block_threshold_xof: int = Field(ge=0, le=SEUIL_MAX_XOF)
