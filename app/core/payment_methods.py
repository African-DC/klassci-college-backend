"""Les moyens de paiement : lesquels existent, dans quel ordre, comment ils s'appellent.

Source unique. Le modele, les schemas, la caisse, les PDF et les permissions
lisent tous d'ici — trois copies de la meme liste finissaient toujours par
diverger, et c'est un total d'argent qui payait la difference.

Deux familles distinctes :

* `SELECTABLE_METHODS` — ce qu'une caissiere peut saisir aujourd'hui.
* `HISTORICAL_METHODS` — ce qui existe en base sans plus etre saisissable.
  `mobile_money` en fait partie depuis que les quatre operateurs ivoiriens
  sont distingues. Les versements deja enregistres sous cette valeur ne sont
  PAS reecrits : personne ne peut savoir apres coup si tel versement etait
  Wave ou Moov Money, et un recu deja remis a une famille cesserait de
  correspondre au papier qu'elle detient. Ils restent donc lisibles, comptes
  et imprimes tels quels.
"""

from typing import Final

#: Ordre d'affichage, par frequence reelle au guichet ivoirien et NON par
#: ordre alphabetique. Les especes d'abord parce que c'est le cas courant au
#: comptoir, puis les operateurs mobile money par part de marche (Wave devant,
#: MTN MoMo ensuite, Orange Money et Moov Money derriere), et enfin les moyens
#: bancaires, rares au guichet d'un college.
#: Merci de ne PAS re-trier alphabetiquement : ce serait ranger le plus rare
#: devant le plus frequent dans un selecteur utilise cinquante fois par jour.
SELECTABLE_METHODS: Final[tuple[str, ...]] = (
    "cash",
    "wave",
    "mtn_momo",
    "orange_money",
    "moov_money",
    "bank_transfer",
    "cheque",
)

#: Valeurs encore presentes en base mais retirees de la saisie.
HISTORICAL_METHODS: Final[tuple[str, ...]] = ("mobile_money",)

#: Tout ce qu'un etat financier peut rencontrer. L'ordre place l'historique en
#: dernier : c'est une ligne qui s'eteint a mesure que les annees passent.
DISPLAY_ORDER: Final[tuple[str, ...]] = SELECTABLE_METHODS + HISTORICAL_METHODS

#: Les moyens qui engagent un tiroir physique, donc une journee de caisse
#: ouverte et un comptage en fin de journee. Tous les autres laissent une
#: trace bancaire ou operateur : il n'y a rien a compter le soir.
DRAWER_METHODS: Final[frozenset[str]] = frozenset({"cash"})

#: Noms commerciaux, ecrits comme les operateurs les ecrivent. `mobile_money`
#: garde son libelle d'origine : il figure tel quel sur des recus deja remis.
PAYMENT_METHOD_LABELS_FR: Final[dict[str, str]] = {
    "cash": "Espèces",
    "wave": "Wave",
    "mtn_momo": "MTN MoMo",
    "orange_money": "Orange Money",
    "moov_money": "Moov Money",
    "bank_transfer": "Virement bancaire",
    "cheque": "Chèque",
    "mobile_money": "Mobile Money",
}

#: Prefixe des permissions « ce role peut encaisser par ce moyen ».
METHOD_PERMISSION_PREFIX: Final[str] = "payments:method:"


def method_permission(method: str) -> str:
    """Slug de la permission qui autorise l'encaissement par ce moyen."""
    return f"{METHOD_PERMISSION_PREFIX}{method}"


def method_label(key: str) -> str:
    """Libelle FR d'un moyen (cash → Espèces).

    Repli sur la cle brute plutot que sur un « Autre » fourre-tout : une
    valeur inconnue doit se voir dans le document, pas se fondre dans une
    categorie qui ferait mentir le total.
    """
    return PAYMENT_METHOD_LABELS_FR.get(key, key)


def ordered_methods(present: object) -> list[str]:
    """Trie des moyens selon `DISPLAY_ORDER`, sans jamais en perdre un.

    Les cles connues sortent dans l'ordre metier ; celles qui ne le sont pas
    suivent, triees, plutot que d'etre silencieusement omises. Une ventilation
    qui laisse tomber une ligne ne colle plus a son propre total, et c'est
    invisible tant que personne n'additionne a la main.
    """
    keys = {str(k) for k in present}  # type: ignore[union-attr]
    known = [m for m in DISPLAY_ORDER if m in keys]
    unknown = sorted(keys - set(DISPLAY_ORDER))
    return known + unknown
